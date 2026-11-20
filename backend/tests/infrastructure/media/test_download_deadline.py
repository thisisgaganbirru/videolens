"""Wall-clock deadline on link downloads, the bounded download pool, and the
shared kill-on-timeout/cancel subprocess helper. No real network; the
subprocess tests run this interpreter, never ffmpeg."""

import asyncio
import io
import os
import shutil
import socket
import ssl
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
from app.infrastructure.media.net import PinnedHTTPSConnection
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

        async def deadline_with_fake_clock(seconds, fn, *args, run_budget=False):
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


def _self_signed_pair(directory: str) -> tuple[str, str]:
    """A throwaway localhost certificate, made with `cryptography` (already
    installed through PyJWT[crypto]; no new dependency)."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = os.path.join(directory, "cert.pem")
    key_path = os.path.join(directory, "key.pem")
    with open(cert_path, "wb") as handle:
        handle.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as handle:
        handle.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    return cert_path, key_path


class _LoopbackTLS:
    """A one-connection TLS server on 127.0.0.1 that answers with headers for
    a 1000-byte body and then (with `trickle`) sends a byte every 0.5 s."""

    def __init__(self, test: unittest.TestCase, *, trickle: bool = True) -> None:
        directory = tempfile.mkdtemp()
        test.addCleanup(shutil.rmtree, directory, True)
        cert_path, key_path = _self_signed_pair(directory)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert_path, key_path)
        self.client_context = ssl.create_default_context(cafile=cert_path)
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(10)
        test.addCleanup(self._listener.close)
        self.port = self._listener.getsockname()[1]
        self._stop = threading.Event()
        test.addCleanup(self._stop.set)
        threading.Thread(target=self._serve, args=(server_context, trickle), daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _serve(self, context: ssl.SSLContext, trickle: bool) -> None:
        try:
            raw, _ = self._listener.accept()
            with context.wrap_socket(raw, server_side=True) as conn:
                if not trickle:
                    self._stop.wait(10)
                    return
                conn.recv(4096)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
                for _ in range(1000):
                    if self._stop.is_set():
                        return
                    conn.sendall(b"a")
                    time.sleep(0.5)
        except OSError:
            return


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

    def test_firing_ends_a_blocked_tls_read(self) -> None:
        # wrap_socket detaches the raw socket, so tracking only that one made
        # the shutdown a no-op for HTTPS (2026-11-20 re-review): a loopback
        # TLS server that sends headers and then trickles the body.
        tls = _LoopbackTLS(self)
        conn = PinnedHTTPSConnection(
            "localhost", tls.port, timeout=10, context=tls.client_context, pinned_address="127.0.0.1"
        )
        self.addCleanup(conn.close)
        outcome = []

        def read_body():
            with DownloadDeadline(0.5):
                conn.request("GET", "/")
                response = conn.getresponse()
                started = time.monotonic()
                try:
                    response.read()
                    outcome.append(("returned", time.monotonic() - started))
                except Exception as exc:  # noqa: BLE001 - any end is the point
                    outcome.append((type(exc).__name__, time.monotonic() - started))

        reader = threading.Thread(target=read_body, daemon=True)
        reader.start()
        reader.join(8)
        stuck = reader.is_alive()
        # Stop the server either way, so a regression fails instead of hanging.
        tls.stop()
        reader.join(5)
        self.assertFalse(stuck, "the deadline did not end the TLS read")
        self.assertLess(outcome[0][1], 5)

    def test_the_tls_socket_is_tracked_not_the_detached_raw_one(self) -> None:
        tls = _LoopbackTLS(self, trickle=False)
        conn = PinnedHTTPSConnection(
            "localhost", tls.port, timeout=10, context=tls.client_context, pinned_address="127.0.0.1"
        )
        self.addCleanup(conn.close)
        with DownloadDeadline(60) as deadline:
            conn.connect()
            tracked = list(deadline._sockets)
        self.assertIn(conn.sock, tracked)
        self.assertIsInstance(conn.sock, ssl.SSLSocket)

    def test_no_deadline_outside_a_download(self) -> None:
        self.assertIsNone(deadline_module.current_deadline())
        track_socket(MagicMock())  # a no-op, never an error


class RunBudgetTests(unittest.IsolatedAsyncioTestCase):
    """One download budget per run (2026-11-20 re-review): yt-dlp 300 s +
    direct HTTP 300 s + captions 300 s used to add up to 900 s, past the
    600 s job timeout."""

    async def test_without_a_budget_each_download_gets_its_full_deadline(self) -> None:
        seconds = await run_download(5, lambda deadline: deadline.seconds, run_budget=True)
        self.assertEqual(seconds, 5)

    async def test_budgeted_downloads_get_only_what_is_left(self) -> None:
        deadline_module.start_run_budget(1.0)
        first = await run_download(300, lambda deadline: deadline.seconds, run_budget=True)
        self.assertLessEqual(first, 1.0)
        # A download outside the budget (the poster fetch) is not clamped.
        self.assertEqual(await run_download(10, lambda deadline: deadline.seconds), 10)

    async def test_a_spent_budget_refuses_the_next_route_at_once(self) -> None:
        deadline_module.start_run_budget(0.0)
        called = []
        with self.assertRaises(DownloadDeadlineExceeded):
            await run_download(300, lambda deadline: called.append(1), run_budget=True)
        self.assertEqual(called, [])

    async def test_the_budget_belongs_to_the_runs_own_task(self) -> None:
        async def a_run():
            deadline_module.start_run_budget(0.0)

        await asyncio.create_task(a_run())
        # Another run (another task) never sees it.
        self.assertIsNone(deadline_module.run_budget_remaining())

    async def test_media_service_shares_one_budget_across_routes_and_captions(self) -> None:
        from app.infrastructure.media.service import MediaService

        temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_dir, True)
        service = MediaService(Settings(temp_dir=temp_dir, download_deadline_seconds=300))
        clock = FakeClock()
        given = []

        async def fake_run_download(seconds, fn, *args, run_budget=False):
            # Each route "uses" 200 s of its deadline before failing.
            remaining = deadline_module.run_budget_remaining(clock=clock)
            limit = seconds if remaining is None or not run_budget else min(seconds, remaining)
            given.append(limit)
            clock.now += min(200, limit)
            raise DownloadDeadlineExceeded("slow")

        real_start = deadline_module.start_run_budget
        with patch.object(ytdlp_downloader, "validate_public_url"), patch.object(
            ytdlp_downloader, "_media_binary", return_value="/usr/bin/ffmpeg"
        ), patch.object(ytdlp_downloader, "run_download", fake_run_download), patch(
            "app.infrastructure.media.resolvers.direct_http.validate_public_url"
        ), patch(
            "app.infrastructure.media.resolvers.direct_http.run_download", fake_run_download
        ), patch(
            "app.infrastructure.media.captions.run_download", fake_run_download
        ), patch(
            "app.infrastructure.media.captions.validate_public_url"
        ), patch(
            "app.infrastructure.media.service.start_run_budget",
            lambda seconds: real_start(seconds, clock=clock),
        ):
            with self.assertRaises(MediaValidationError):
                await service.download_url("run-1", "https://cdn.test/clip.mp4")
            self.assertIsNone(await service.fetch_captions("https://cdn.test/clip.mp4"))
        # yt-dlp got 300, the plain GET what was left (100), captions nothing.
        self.assertEqual(given, [300, 100, 0])
        self.assertLessEqual(clock.now, 300)


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
