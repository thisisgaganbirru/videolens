"""A total wall-clock bound for one blocking download, and the bounded pool
downloads run on.

The socket timeouts on every fetch are per read: a server trickling a byte
just inside them keeps a read alive for ever, and the thread it runs on with
it (arq's job timeout cancels the coroutine, never the thread). So a
download runs inside a `DownloadDeadline`:

- the read loops and yt-dlp's hooks call `check()` and stop with the
  module's normal failure once it has passed;
- every connection `net.py` opens in that thread is tracked, and when the
  deadline fires a timer shuts those sockets down, so even a single read
  that is still blocked (a slow page during yt-dlp's info extraction, say)
  returns at once instead of after its own timeout.

Downloads run on `DOWNLOAD_EXECUTOR`, not the default `to_thread` pool, so
however many are stuck they can never starve the DNS checks, S3 calls and
token checks that share that pool.

One run can try several routes in turn (yt-dlp, then a plain GET, then the
caption fallback). Each with its own full deadline added up past the job
timeout, so the routes share one budget per run: `start_run_budget` (called
once by `MediaService.download_url`) records when the run's downloading has
to be over, and `run_download(..., run_budget=True)` gives each route only
what is left of it. The budget lives in a ContextVar, so it follows the run's
own task and never another run's.
"""

import asyncio
import contextvars
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# Each worker job runs at most one download at a time (media, then captions
# if it failed), and WORKER_MAX_JOBS is small; the headroom covers the API's
# local mode, where runs share the process.
DOWNLOAD_THREADS = 8
DOWNLOAD_EXECUTOR = ThreadPoolExecutor(max_workers=DOWNLOAD_THREADS, thread_name_prefix="videolens-download")

_local = threading.local()

# Monotonic time by which this run's link downloading has to be over; None
# outside a run (each download then gets its own full deadline).
_run_budget_ends_at: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "videolens_run_download_budget", default=None
)


class DownloadDeadlineExceeded(Exception):
    """The download ran past its wall-clock deadline. Each module turns it
    into its own failure (a MediaValidationError, or a caption miss)."""


class DownloadDeadline:
    def __init__(self, seconds: float, *, clock=time.monotonic) -> None:
        self.seconds = seconds
        self._clock = clock
        self._ends_at = clock() + seconds
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []
        self._fired = False
        self._timer: threading.Timer | None = None

    @property
    def remaining(self) -> float:
        return max(0.0, self._ends_at - self._clock())

    @property
    def expired(self) -> bool:
        return self._fired or self._clock() >= self._ends_at

    def check(self) -> None:
        if self.expired:
            raise DownloadDeadlineExceeded(f"download took longer than {self.seconds:g}s")

    def track(self, sock: socket.socket) -> None:
        with self._lock:
            fired = self._fired
            if not fired:
                self._sockets.append(sock)
        if fired:
            _shutdown(sock)

    def _fire(self) -> None:
        with self._lock:
            self._fired = True
            sockets, self._sockets = self._sockets, []
        for sock in sockets:
            _shutdown(sock)

    def __enter__(self) -> "DownloadDeadline":
        _local.deadline = self
        self._timer = threading.Timer(self.seconds, self._fire)
        self._timer.daemon = True
        self._timer.start()
        return self

    def __exit__(self, *exc) -> None:
        _local.deadline = None
        if self._timer is not None:
            self._timer.cancel()
        with self._lock:
            self._sockets = []


def _shutdown(sock: socket.socket) -> None:
    # shutdown, not close, on Linux (where the workers run): it wakes a recv
    # blocked in another thread (close does not), and the owner still closes
    # the socket as usual. Windows only wakes a blocked recv on close.
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    if os.name == "nt":
        try:
            sock.close()
        except OSError:
            pass


def current_deadline() -> DownloadDeadline | None:
    return getattr(_local, "deadline", None)


def track_socket(sock: socket.socket) -> None:
    """Called by `net.py` for every connection it opens: bound by the
    deadline of the download running in this thread, if there is one."""
    deadline = current_deadline()
    if deadline is not None:
        deadline.track(sock)


def start_run_budget(seconds: float, *, clock=time.monotonic) -> None:
    """Start the run's one download budget: every `run_budget=True` download
    after this in the same task shares `seconds` in total."""
    _run_budget_ends_at.set(clock() + seconds)


def run_budget_remaining(*, clock=time.monotonic) -> float | None:
    ends_at = _run_budget_ends_at.get()
    return None if ends_at is None else max(0.0, ends_at - clock())


async def run_download(seconds: float, fn, *args, run_budget: bool = False):
    """Run blocking `fn(deadline, *args)` on the download pool inside a
    fresh deadline of `seconds` - or, with `run_budget`, of whatever is left
    of the run's budget when the thread starts, if that is less. Time spent
    queued for a thread counts against the budget."""
    # Read here: run_in_executor does not carry the context into the thread.
    ends_at = _run_budget_ends_at.get() if run_budget else None

    def call():
        limit = seconds
        if ends_at is not None:
            left = ends_at - time.monotonic()
            if left <= 0:
                raise DownloadDeadlineExceeded("the run's download budget was already spent")
            limit = min(seconds, left)
        with DownloadDeadline(limit) as deadline:
            return fn(deadline, *args)

    return await asyncio.get_running_loop().run_in_executor(DOWNLOAD_EXECUTOR, call)
