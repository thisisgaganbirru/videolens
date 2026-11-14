"""Every media enforcement point honours the run's own `MediaLimits`, and
falls back to the deployment's standard settings when given none."""

import io
import os
import shutil
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.domain.entitlements import MediaLimits, MediaTier
from app.domain.errors import MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.media import captions, ffmpeg, uploads, ytdlp_downloader
from app.infrastructure.media.resolvers.direct_http import DirectHttpResolver

PUBLIC_ADDRESS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
BIGGER = MediaLimits(tier=MediaTier.SIGNED_IN_BYOK, max_duration_seconds=600, max_file_size_mb=3)
STANDARD_WITH_HINT = MediaLimits(
    tier=MediaTier.STANDARD,
    max_duration_seconds=180,
    max_file_size_mb=1,
    upgrade_action="Sign in",
    upgrade_max_duration_seconds=600,
    upgrade_max_file_size_mb=3,
)
MB = 1024 * 1024


class _Upload:
    def __init__(self, size: int, filename: str = "clip.mp4") -> None:
        self.filename = filename
        self._stream = io.BytesIO(b"x" * size)

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    async def close(self) -> None:
        pass


class UploadSizeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        # Standard: 1 MB, so the test files stay small.
        self.settings = Settings(temp_dir=self.temp_dir, max_file_size_mb=1)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_standard_cap_without_limits(self) -> None:
        with self.assertRaisesRegex(MediaValidationError, "over the 1MB limit"):
            await uploads.save_upload(self.settings, "r1", _Upload(2 * MB))

    async def test_bigger_limits_admit_what_standard_refuses(self) -> None:
        saved = await uploads.save_upload(self.settings, "r1", _Upload(2 * MB), BIGGER)
        self.assertEqual(saved.size_bytes, 2 * MB)
        with self.assertRaisesRegex(MediaValidationError, "over the 3MB limit"):
            await uploads.save_upload(self.settings, "r2", _Upload(3 * MB + 1), BIGGER)

    async def test_hint_reaches_the_message(self) -> None:
        with self.assertRaises(MediaValidationError) as caught:
            await uploads.save_upload(self.settings, "r1", _Upload(2 * MB), STANDARD_WITH_HINT)
        self.assertEqual(str(caught.exception), "That file is over the 1MB limit. Sign in for files up to 3MB.")


class DurationProbeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = Settings(temp_dir=tempfile.gettempdir())

    async def _enforce(self, seconds: float, limits=None) -> float:
        async def probe(settings, path):
            return seconds

        with patch.object(ffmpeg, "probe_duration_seconds", probe), patch.object(ffmpeg, "cleanup_run_dir"):
            return await ffmpeg.enforce_duration_cap(self.settings, "r1", "/x.mp4", limits)

    async def test_standard_without_limits(self) -> None:
        self.assertEqual(await self._enforce(179), 179)
        with self.assertRaisesRegex(MediaValidationError, "This video is 3:01 long. The limit is 3:00.$"):
            await self._enforce(181)

    async def test_bigger_limits(self) -> None:
        self.assertEqual(await self._enforce(599, BIGGER), 599)
        with self.assertRaisesRegex(MediaValidationError, "The limit is 10:00."):
            await self._enforce(601, BIGGER)

    async def test_hint_only_when_the_bigger_limit_would_fit(self) -> None:
        with self.assertRaises(MediaValidationError) as caught:
            await self._enforce(300, STANDARD_WITH_HINT)
        self.assertTrue(str(caught.exception).endswith("Sign in for videos up to 10:00."))
        with self.assertRaises(MediaValidationError) as caught:
            await self._enforce(601, STANDARD_WITH_HINT)
        self.assertNotIn("Sign in", str(caught.exception))


class YtDlpLimitTests(unittest.IsolatedAsyncioTestCase):
    async def _download(self, limits, size: int):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(temp_dir=temp_dir, max_file_size_mb=1)
            path = os.path.join(temp_dir, "download.mp4")
            with open(path, "wb") as fh:
                fh.write(b"x" * size)
            downloader = MagicMock()
            downloader.__enter__.return_value = downloader
            downloader.__exit__.return_value = False
            downloader.extract_info.return_value = {"requested_downloads": [{"filepath": path}]}
            downloader.prepare_filename.return_value = path
            seen = {}

            def make(options):
                seen.update(options)
                return downloader

            with patch.object(ytdlp_downloader, "validate_public_url"), patch.object(
                ytdlp_downloader, "_media_binary", return_value="/usr/bin/ffmpeg"
            ), patch.object(ytdlp_downloader, "YoutubeDL", side_effect=make):
                saved = await ytdlp_downloader.download_url(settings, "r1", "https://x.test/v", limits)
            return saved, seen

    async def test_max_filesize_follows_the_limits(self) -> None:
        saved, options = await self._download(BIGGER, 2 * MB)
        self.assertEqual(options["max_filesize"], 3 * MB)
        self.assertEqual(saved.size_bytes, 2 * MB)

    async def test_standard_post_download_check(self) -> None:
        with self.assertRaisesRegex(MediaValidationError, "That video is over the 1MB limit."):
            await self._download(None, 2 * MB)


class DirectHttpLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.resolver = DirectHttpResolver(Settings(temp_dir=self.temp_dir, max_file_size_mb=1))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PUBLIC_ADDRESS)
    @patch("app.infrastructure.media.resolvers.direct_http.build_public_opener")
    async def test_bigger_limits_admit_a_larger_file(self, build_opener, _dns) -> None:
        stream = io.BytesIO(b"x" * (2 * MB))
        response = MagicMock()
        response.read.side_effect = stream.read
        response.headers = {}
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        build_opener.return_value.open.return_value = response

        saved = await self.resolver.fetch("r1", "https://cdn.test/clip.mp4", BIGGER)
        self.assertEqual(saved.size_bytes, 2 * MB)


class CaptionLimitTests(unittest.IsolatedAsyncioTestCase):
    async def _fetch(self, duration: int, limits=None):
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.__exit__.return_value = False
        downloader.extract_info.return_value = {
            "duration": duration,
            "subtitles": {"en": [{"ext": "vtt", "url": "https://x.test/en.vtt"}]},
        }
        downloader.urlopen.return_value.read.return_value = b"WEBVTT\n\n00:00.000 --> 00:01.000\nhello there\n"
        with patch.object(captions, "validate_public_url"), patch.object(
            captions, "YoutubeDL", return_value=downloader
        ):
            return await captions.fetch_captions(Settings(), "https://x.test/v", limits)

    async def test_standard_cap_without_limits(self) -> None:
        self.assertIsNotNone(await self._fetch(170))
        self.assertIsNone(await self._fetch(400))

    async def test_the_runs_own_limit_applies(self) -> None:
        self.assertIsNotNone(await self._fetch(400, BIGGER))
        self.assertIsNone(await self._fetch(601, BIGGER))


if __name__ == "__main__":
    unittest.main()
