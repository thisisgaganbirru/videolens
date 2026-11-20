"""An upload named `.mp4` whose bytes are a playlist (HLS `#EXTM3U`, a DASH
manifest, an `ffconcat` list) rather than media. ffprobe and ffmpeg pick the
demuxer from the content, not the extension, so such a file could make them
open the URLs it lists, from the API (the intake duration probe) and from
the worker (normalize, thumbnails).

The subprocess is faked throughout (`run_process`), so these tests check the
argument lists and the validation order, never a real ffmpeg. The first two
pin what is true today. The last two describe the intended hardening (an
input protocol whitelist on every probe and encode, and a content check that
refuses a playlist before ffprobe ever sees it); neither exists yet, so they
are expected failures (reported in mem/20261120-fix-tests-and-docs.md)."""

import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.domain.errors import MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.media import ffmpeg, uploads

HLS = (
    b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\n"
    b"http://169.254.169.254/latest/meta-data/iam/security-credentials/role\n#EXT-X-ENDLIST\n"
)


class _Upload:
    def __init__(self, body: bytes, filename: str = "clip.mp4") -> None:
        self.filename = filename
        self._body = body

    async def read(self, size: int = -1) -> bytes:
        chunk, self._body = self._body[:size], self._body[size:]
        return chunk

    async def close(self) -> None:
        pass


class HostileInputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.settings = Settings(_env_file=None, temp_dir=self._dir.name)
        # No ffmpeg needed on PATH: the binary is never run.
        patcher = patch.object(ffmpeg, "_media_binary", lambda settings, name: name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fake_process(self, *results):
        patcher = patch.object(ffmpeg, "run_process", AsyncMock(side_effect=list(results)))
        fake = patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    async def _commands(self, path: str) -> list[list[str]]:
        """Every argv the intake probe and the normalize step would run."""
        fake = self._fake_process((0, b"10.0\n", b""), (0, b"video\n", b""), (0, b"", b""))
        await ffmpeg.probe_duration_seconds(self.settings, path)
        await ffmpeg.normalize_media(self.settings, path, self._dir.name)
        return [call.args[0] for call in fake.await_args_list]

    async def test_every_command_is_an_argument_list_with_the_path_as_one_element(self) -> None:
        path = f"{self._dir.name}/upload.mp4; curl http://169.254.169.254"
        for argv in await self._commands(path):
            with self.subTest(argv=argv[0]):
                self.assertIsInstance(argv, list)
                self.assertEqual(argv.count(path), 1)

    async def test_a_playlist_ffprobe_cannot_read_is_a_plain_validation_error(self) -> None:
        self._fake_process((1, b"", b"moov atom not found\nInvalid data found when processing input"))
        with self.assertRaises(MediaValidationError) as caught:
            await ffmpeg.probe_duration_seconds(self.settings, f"{self._dir.name}/upload.mp4")
        self.assertNotIn("moov", str(caught.exception))
        self.assertIn("moov atom not found", caught.exception.log_detail)

    @unittest.expectedFailure
    async def test_every_probe_and_encode_restricts_input_protocols(self) -> None:
        # Intended: `-protocol_whitelist file` (no http, tcp, crypto...) before
        # the input, so a playlist cannot make ffmpeg fetch anything.
        for argv in await self._commands(f"{self._dir.name}/upload.mp4"):
            with self.subTest(argv=argv[0]):
                self.assertIn("-protocol_whitelist", argv)
                allowed = argv[argv.index("-protocol_whitelist") + 1].split(",")
                self.assertNotIn("http", allowed)
                self.assertNotIn("https", allowed)
                self.assertNotIn("tcp", allowed)

    @unittest.expectedFailure
    async def test_a_playlist_named_mp4_is_refused_at_intake_before_ffprobe(self) -> None:
        # An ffprobe that would happily report a duration for it.
        fake = self._fake_process((0, b"10.0\n", b""))
        with self.assertRaises(MediaValidationError):
            saved = await uploads.save_upload(self.settings, "run-1", _Upload(HLS))
            await ffmpeg.enforce_duration_cap(self.settings, "run-1", saved.path)
        fake.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
