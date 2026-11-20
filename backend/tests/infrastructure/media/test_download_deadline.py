"""Wall-clock deadline on link downloads, the bounded download pool, and the
shared kill-on-timeout/cancel subprocess helper. No real network; the
subprocess tests run this interpreter, never ffmpeg."""

import asyncio
import io
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


from app.domain.errors import MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.media import deadline as deadline_module
from app.infrastructure.media import ffmpeg, ytdlp_downloader
from app.infrastructure.media.deadline import (
    DOWNLOAD_EXECUTOR,
    DownloadDeadline,
    DownloadDeadlineExceeded,
    run_download,
    track_socket,
)
from app.infrastructure.media.process import run_process
from app.infrastructure.media.resolvers.direct_http import DirectHttpResolver
from app.infrastructure.media.ytdlp_net import GuardedYoutubeDL

PUBLIC_ADDRESS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class DirectHttpDeadlineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.resolver = DirectHttpResolver(Settings(temp_dir=self.temp_dir, max_file_size_mb=50))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PUBLIC_ADDRESS)
    @patch("app.infrastructure.media.resolvers.direct_http.urllib.request.build_opener")
    def test_a_trickling_server_trips_the_deadline_in_the_read_loop(self, build_opener, _dns) -> None:
        clock = FakeClock()
        deadline = DownloadDeadline(60, clock=clock)
        reads = []

        def trickle(_size):
            # One byte per read, ten seconds apart: every socket read is
            # well inside its own timeout, the whole never ends.
            clock.now += 10
            reads.append(1)
            return b"x"

        response = MagicMock()
        response.read1.side_effect = trickle
        response.headers = {}
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        build_opener.return_value.open.return_value = response

        with self.assertRaises(DownloadDeadlineExceeded):
            self.resolver._download(deadline, "https://cdn.test/clip.mp4", self.temp_dir)
        self.assertEqual(len(reads), 6)

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PUBLIC_ADDRESS)
    @patch("app.infrastructure.media.resolvers.direct_http.urllib.request.build_opener")
    def test_a_body_cut_off_by_the_deadline_is_not_a_download(self, build_opener, _dns) -> None:
        clock = FakeClock()
        deadline = DownloadDeadline(60, clock=clock)
        stream = io.BytesIO(b"partial")

        def read(size):
            data = stream.read(size)
            if not data:
                # The timer shut the socket: reads as a clean end of file.
                clock.now = 61
            return data

        response = MagicMock()
        response.read1.side_effect = read
        response.headers = {}
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        build_opener.return_value.open.return_value = response

        with self.assertRaises(DownloadDeadlineExceeded):
            self.resolver._download(deadline, "https://cdn.test/clip.mp4", self.temp_dir)


class DirectHttpFetchDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_turns_the_deadline_into_the_resolvers_failure(self) -> None:
        temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_dir, True)
        resolver = DirectHttpResolver(Settings(temp_dir=temp_dir, download_deadline_seconds=5))

        def slow(deadline, *_args):
            raise DownloadDeadlineExceeded("download took longer than 5s")

        with patch("app.infrastructure.media.resolvers.direct_http.validate_public_url"), patch.object(
            resolver, "_download", slow
        ):
            with self.assertRaisesRegex(MediaValidationError, "took too long"):
                await resolver.fetch("run-1", "https://cdn.test/clip.mp4")
        self.assertFalse(os.path.exists(os.path.join(temp_dir, "run-1")))


class YtDlpDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_progress_hook_trips_the_deadline(self) -> None:
        clock = FakeClock()
        temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_dir, True)
        settings = Settings(temp_dir=temp_dir, download_deadline_seconds=60)

        def make(options, deadline=None):
            downloader = MagicMock()
            downloader.__enter__.return_value = downloader
            downloader.__exit__.return_value = False

            def extract_info(url, download):
                # A slow stream: the hook sees 10 s pass per chunk.
                for _ in range(100):
                    clock.now += 10
                    for hook in options["progress_hooks"]:
                        hook({"downloaded_bytes": 1})
                return {}

            downloader.extract_info.side_effect = extract_info
            return downloader

        async def deadline_with_fake_clock(seconds, fn, *args):
            with DownloadDeadline(seconds, clock=clock) as deadline:
                return fn(deadline, *args)

        with patch.object(ytdlp_downloader, "validate_public_url"), patch.object(
            ytdlp_downloader, "_media_binary", return_value="/usr/bin/ffmpeg"
        ), patch.object(ytdlp_downloader, "GuardedYoutubeDL", side_effect=make), patch.object(
            ytdlp_downloader, "run_download", deadline_with_fake_clock
        ):
            with self.assertRaisesRegex(MediaValidationError, "took too long") as caught:
                await ytdlp_downloader.download_url(settings, "run-1", "https://www.youtube.com/watch?v=x")
        self.assertIn("deadline", caught.exception.log_detail)
        self.assertEqual(clock.now, 60)

    def test_every_yt_dlp_request_checks_the_deadline(self) -> None:
        clock = FakeClock()
        deadline = DownloadDeadline(60, clock=clock)
        ydl = GuardedYoutubeDL({"quiet": True, "no_warnings": True, "proxy": ""}, deadline=deadline)
        self.addCleanup(ydl.close)
        clock.now = 61
        # Refused before the request director is ever asked: info extraction
        # cannot start another request past the deadline.
        with patch.object(ydl, "_request_director") as director:
            with self.assertRaises(DownloadDeadlineExceeded):
                ydl.urlopen("https://www.youtube.com/watch?v=x")
        director.send.assert_not_called()


class DeadlineMechanicsTests(unittest.TestCase):
    def test_firing_shuts_down_tracked_sockets(self) -> None:
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        received = []

        def blocked_read():
            # Nothing is ever sent: only the deadline can end this recv
            # (an end of file on Linux, an error on Windows).
            try:
                received.append(left.recv(1))
            except OSError:
                received.append(b"")

        with DownloadDeadline(0.2) as deadline:
            track_socket(left)
            reader = threading.Thread(target=blocked_read, daemon=True)
            reader.start()
            reader.join(5)
            self.assertFalse(reader.is_alive())
            self.assertTrue(deadline.expired)
        self.assertEqual(received, [b""])

    def test_no_deadline_outside_a_download(self) -> None:
        self.assertIsNone(deadline_module.current_deadline())
        track_socket(MagicMock())  # a no-op, never an error


class DownloadPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_downloads_run_on_the_dedicated_pool(self) -> None:
        def which_thread(deadline):
            self.assertIs(deadline_module.current_deadline(), deadline)
            return threading.current_thread().name

        name = await run_download(5, which_thread)
        self.assertTrue(name.startswith("videolens-download"))
        self.assertEqual(DOWNLOAD_EXECUTOR._max_workers, deadline_module.DOWNLOAD_THREADS)

    async def test_the_deadline_is_cleared_after_the_download(self) -> None:
        def leaves(deadline):
            return None

        await run_download(5, leaves)
        thread_deadline = await asyncio.get_running_loop().run_in_executor(
            DOWNLOAD_EXECUTOR, deadline_module.current_deadline
        )
        self.assertIsNone(thread_deadline)


_SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class RunProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_output_and_code(self) -> None:
        code, stdout, _ = await run_process([sys.executable, "-c", "print('hi')"], timeout=30)
        self.assertEqual(code, 0)
        self.assertEqual(stdout.strip(), b"hi")

    async def test_kills_the_process_on_timeout(self) -> None:
        spawned = []
        real = asyncio.create_subprocess_exec

        async def spy(*args, **kwargs):
            proc = await real(*args, **kwargs)
            spawned.append(proc)
            return proc

        started = time.monotonic()
        with patch("app.infrastructure.media.process.asyncio.create_subprocess_exec", spy):
            with self.assertRaises(TimeoutError):
                await run_process(_SLEEPER, timeout=0.5)
        self.assertLess(time.monotonic() - started, 15)
        self.assertIsNotNone(spawned[0].returncode)
        self.assertFalse(_alive(spawned[0].pid))

    async def test_kills_the_process_on_cancellation(self) -> None:
        spawned = []
        real = asyncio.create_subprocess_exec

        async def spy(*args, **kwargs):
            proc = await real(*args, **kwargs)
            spawned.append(proc)
            return proc

        with patch("app.infrastructure.media.process.asyncio.create_subprocess_exec", spy):
            task = asyncio.create_task(run_process(_SLEEPER, timeout=60))
            while not spawned:
                await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(spawned[0].returncode)
        self.assertFalse(_alive(spawned[0].pid))

    async def test_a_hung_ffprobe_is_a_validation_error(self) -> None:
        async def hung(*_args, **_kwargs):
            raise TimeoutError()

        with patch.object(ffmpeg, "run_process", hung), patch.object(ffmpeg, "_media_binary", return_value="ffprobe"):
            with self.assertRaisesRegex(MediaValidationError, "couldn't be read") as caught:
                await ffmpeg.probe_duration_seconds(Settings(), "x.mp4")
        self.assertIn("timed out", caught.exception.log_detail)

    async def test_a_hung_encode_is_a_validation_error(self) -> None:
        async def probe_then_hang(command, *, timeout, stdin=None):
            if "-show_entries" in command:
                return 0, b"video\n", b""
            raise TimeoutError()

        with patch.object(ffmpeg, "run_process", probe_then_hang), patch.object(
            ffmpeg, "_media_binary", return_value="ffmpeg"
        ):
            with self.assertRaisesRegex(MediaValidationError, "couldn't be processed"):
                await ffmpeg.normalize_media(Settings(), "in.mp4", tempfile.gettempdir())


if __name__ == "__main__":
    unittest.main()
