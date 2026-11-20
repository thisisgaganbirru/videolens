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
"""

import asyncio
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


async def run_download(seconds: float, fn, *args):
    """Run blocking `fn(deadline, *args)` on the download pool inside a
    fresh deadline of `seconds`."""

    def call():
        with DownloadDeadline(seconds) as deadline:
            return fn(deadline, *args)

    return await asyncio.get_running_loop().run_in_executor(DOWNLOAD_EXECUTOR, call)
