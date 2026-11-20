"""An upload named `.mp4` whose bytes are a playlist (HLS `#EXTM3U`, a DASH
manifest, an `ffconcat` list) rather than media. ffprobe and ffmpeg pick the
demuxer from the content, not the extension, so such a file could make them
open the URLs it lists, from the API (the intake duration probe) and from
the worker (normalize, thumbnails).

`HostileInputTests` fake the subprocess (`run_process`), so they check the
argument lists and the validation order; `RealBinaryTests` (skipped without
ffmpeg on PATH) run the same commands on the real binaries. Two of the fakes
were expected failures until 2026-11-20, when the hardening they describe
landed: `-protocol_whitelist file` on every probe and encode, and a content
check that refuses a playlist before ffprobe ever sees it."""

import os
import shutil
import subprocess
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

    async def test_a_playlist_named_mp4_is_refused_at_intake_before_ffprobe(self) -> None:
        # An ffprobe that would happily report a duration for it.
        fake = self._fake_process((0, b"10.0\n", b""))
        with self.assertRaises(MediaValidationError):
            saved = await uploads.save_upload(self.settings, "run-1", _Upload(HLS))
            await ffmpeg.enforce_duration_cap(self.settings, "run-1", saved.path)
        fake.assert_not_awaited()


    async def test_the_content_check_lets_real_media_through_to_ffprobe(self) -> None:
        # An MP4 opens with a box size and `ftyp`; an MP3 with `ID3`.
        for head in (bytes([0, 0, 0, 0x18]) + b"ftypmp42", b"ID3" + bytes(10)):
            path = f"{self._dir.name}/real.mp4"
            with open(path, "wb") as handle:
                handle.write(head + bytes(100))
            fake = self._fake_process((0, b"10.0\n", b""))
            self.assertEqual(await ffmpeg.probe_duration_seconds(self.settings, path), 10.0)
            fake.assert_awaited_once()

    async def test_a_bom_or_leading_whitespace_does_not_hide_a_playlist(self) -> None:
        path = f"{self._dir.name}/upload.mp4"
        with open(path, "wb") as handle:
            handle.write(bytes([0xEF, 0xBB, 0xBF]) + b"\r\n  ffconcat version 1.0\nfile http://x/\n")
        fake = self._fake_process((0, b"10.0\n", b""))
        with self.assertRaises(MediaValidationError) as caught:
            await ffmpeg.probe_duration_seconds(self.settings, path)
        self.assertIn("playlist", caught.exception.log_detail)
        fake.assert_not_awaited()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg on PATH")
class RealBinaryTests(unittest.IsolatedAsyncioTestCase):
    """The whitelisted commands against the real ffprobe/ffmpeg: real media
    still probes and normalises, and a playlist the content check would miss
    (no signature at the start) cannot open a URL through the whitelist."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.settings = Settings(_env_file=None, temp_dir=self._dir.name)

    def _make(self, name: str, *args: str) -> str:
        path = os.path.join(self._dir.name, name)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args, path], check=True)
        return path

    async def test_real_video_and_audio_probe_and_normalise_with_the_whitelist(self) -> None:
        video = self._make("clip.mp4", "-f", "lavfi", "-i", "testsrc2=d=1:s=160x120", "-c:v", "libx264")
        audio = self._make("tone.mp3", "-f", "lavfi", "-i", "sine=d=1")
        for path, expected in ((video, "normalized.mp4"), (audio, "normalized.mp3")):
            with self.subTest(path=os.path.basename(path)):
                self.assertAlmostEqual(await ffmpeg.probe_duration_seconds(self.settings, path), 1.0, delta=0.2)
                out = await ffmpeg.normalize_media(self.settings, path, self._dir.name)
                self.assertEqual(os.path.basename(out), expected)
                self.assertGreater(os.path.getsize(out), 0)

    async def test_the_whitelist_is_what_the_real_ffprobe_applies(self) -> None:
        # Past the content check, as a playlist it missed would be. Named
        # .m3u8 so ffprobe 8.x opens it as HLS (it will not sniff HLS under
        # .mp4). Its own default list is `file,crypto,data`; the refusal
        # naming `'file'` alone shows ours is the one in force. The segment
        # is a closed loopback port, so nothing could be reached anyway.
        playlist = os.path.join(self._dir.name, "upload.m3u8")
        with open(playlist, "w", encoding="ascii") as handle:
            handle.write(chr(10).join(["#EXTM3U", "#EXT-X-TARGETDURATION:1", "#EXTINF:1,", "http://127.0.0.1:9/x.ts", "#EXT-X-ENDLIST", ""]))
        with patch.object(ffmpeg, "_refuse_playlist", lambda path: None):
            with self.assertRaises(MediaValidationError) as caught:
                await ffmpeg.probe_duration_seconds(self.settings, playlist)
        self.assertIn("not on whitelist 'file'!", caught.exception.log_detail)


if __name__ == "__main__":
    unittest.main()
