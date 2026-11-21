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
# DASH manifests the first content check let through (2026-11-21 re-review):
# a leading XML comment, and a lowercase root. ffprobe sniffs `<mpd` in any
# case anywhere in its probe buffer and opens the file as DASH.
DASH_BODY = (
    b'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT1S">'
    b"<BaseURL>file:///etc/</BaseURL><Period><AdaptationSet><Representation id=\"1\" bandwidth=\"1\">"
    b"<SegmentBase/></Representation></AdaptationSet></Period></MPD>\n"
)
DASH_VARIANTS = (
    b"<!-- generated -->\n" + DASH_BODY,
    DASH_BODY.replace(b"<MPD", b"<mpd").replace(b"</MPD>", b"</mpd>"),
    b"\xef\xbb\xbf\n\t <?XML version='1.0'?>" + DASH_BODY,
    b"  #EXTM3U\n#EXTINF:1,\nfile:///etc/passwd\n",
    b"# a comment line\n",
)
_MP4_PROBE = b"format_name=mov,mp4,m4a,3gp,3g2,mj2\nduration=10.0\n"


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
        fake = self._fake_process((0, _MP4_PROBE, b""), (0, b"video\n", b""), (0, b"", b""))
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
        fake = self._fake_process((0, _MP4_PROBE, b""))
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
            fake = self._fake_process((0, _MP4_PROBE, b""))
            self.assertEqual(await ffmpeg.probe_duration_seconds(self.settings, path), 10.0)
            fake.assert_awaited_once()

    async def test_a_bom_or_leading_whitespace_does_not_hide_a_playlist(self) -> None:
        path = f"{self._dir.name}/upload.mp4"
        with open(path, "wb") as handle:
            handle.write(bytes([0xEF, 0xBB, 0xBF]) + b"\r\n  ffconcat version 1.0\nfile http://x/\n")
        fake = self._fake_process((0, _MP4_PROBE, b""))
        with self.assertRaises(MediaValidationError) as caught:
            await ffmpeg.probe_duration_seconds(self.settings, path)
        self.assertIn("playlist", caught.exception.log_detail)
        fake.assert_not_awaited()

    async def test_a_dash_manifest_in_any_spelling_is_refused_before_ffprobe(self) -> None:
        path = f"{self._dir.name}/upload.mp4"
        for body in DASH_VARIANTS:
            with self.subTest(body=body[:24]):
                with open(path, "wb") as handle:
                    handle.write(body)
                fake = self._fake_process((0, _MP4_PROBE, b""))
                with self.assertRaises(MediaValidationError) as caught:
                    await ffmpeg.probe_duration_seconds(self.settings, path)
                self.assertIn("before ffprobe", caught.exception.log_detail)
                fake.assert_not_awaited()

    async def test_a_large_first_box_whose_size_byte_looks_like_whitespace_is_media(self) -> None:
        # A MOV opening with a ~170 MB `mdat`: size 0x0A3C..., so the first
        # byte is a newline and the second is `<`. Bytes 4-8 are its type.
        path = f"{self._dir.name}/big.mov"
        with open(path, "wb") as handle:
            handle.write(bytes([0x0A, 0x3C, 0x00, 0x10]) + b"mdat" + bytes(100))
        fake = self._fake_process((0, _MP4_PROBE, b""))
        self.assertEqual(await ffmpeg.probe_duration_seconds(self.settings, path), 10.0)
        fake.assert_awaited_once()

    async def test_a_file_ffprobe_opened_as_a_playlist_is_refused(self) -> None:
        # The second line of defence: whatever the content check missed,
        # ffprobe names the demuxer it used.
        path = f"{self._dir.name}/real.mp4"
        with open(path, "wb") as handle:
            handle.write(bytes([0, 0, 0, 0x18]) + b"ftypmp42" + bytes(100))
        for format_name in ("dash", "hls", "concat", "webm_dash_manifest", "imf", "HLS"):
            with self.subTest(format_name=format_name):
                self._fake_process((0, f"format_name={format_name}\nduration=1.0\n".encode(), b""))
                with self.assertRaises(MediaValidationError) as caught:
                    await ffmpeg.probe_duration_seconds(self.settings, path)
                self.assertIn("after ffprobe", caught.exception.log_detail)
        # Even with no duration (its segments did not open).
        self._fake_process((0, b"format_name=dash\nduration=N/A\n", b""))
        with self.assertRaises(MediaValidationError) as caught:
            await ffmpeg.probe_duration_seconds(self.settings, path)
        self.assertIn("after ffprobe", caught.exception.log_detail)

    async def test_the_probe_asks_for_the_demuxer_and_reads_keyed_output(self) -> None:
        path = f"{self._dir.name}/real.mp3"
        with open(path, "wb") as handle:
            handle.write(b"ID3" + bytes(100))
        fake = self._fake_process((0, b"format_name=mp3\nduration=2.5\n", b""))
        self.assertEqual(await ffmpeg.probe_duration_seconds(self.settings, path), 2.5)
        argv = fake.await_args.args[0]
        self.assertEqual(argv[argv.index("-show_entries") + 1], "format=format_name,duration")


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

    async def test_the_real_ffprobe_opening_a_dash_manifest_is_refused(self) -> None:
        # A real DASH set from ffmpeg's own muxer, its manifest rewritten the
        # way the re-review bypassed the first check (a leading comment, a
        # lowercase root) and named .mp4. With the content check patched out,
        # ffprobe opens it as DASH, reads the local segments and reports a
        # duration; the demuxer it names is refused.
        out = subprocess.run(["ffprobe", "-hide_banner", "-demuxers"], capture_output=True, text=True).stdout
        if " dash " not in out:
            self.skipTest("this ffprobe has no DASH demuxer")
        mpd = os.path.join(self._dir.name, "man.mpd")
        subprocess.run(  # the muxer writes its segments to the working directory
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=d=1:s=64x64", "-f", "dash", "man.mpd"],
            check=True, cwd=self._dir.name,
        )
        with open(mpd, "rb") as handle:
            body = handle.read().split(b"?>", 1)[-1].replace(b"<MPD", b"<mpd").replace(b"</MPD>", b"</mpd>")
        manifest = os.path.join(self._dir.name, "upload.mp4")
        with open(manifest, "wb") as handle:
            handle.write(b"<!-- c -->" + body)
        with self.assertRaises(MediaValidationError) as caught:
            await ffmpeg.probe_duration_seconds(self.settings, manifest)
        self.assertIn("before ffprobe", caught.exception.log_detail)
        with patch.object(ffmpeg, "_refuse_playlist", lambda path: None):
            with self.assertRaises(MediaValidationError) as caught:
                await ffmpeg.probe_duration_seconds(self.settings, manifest)
        self.assertIn("after ffprobe", caught.exception.log_detail)
        self.assertIn("dash", caught.exception.log_detail)

    async def test_the_real_ffprobe_reports_format_names_the_check_accepts(self) -> None:
        video = os.path.join(self._dir.name, "clip.mov")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=d=1:s=160x120", video], check=True)
        self.assertAlmostEqual(await ffmpeg.probe_duration_seconds(self.settings, video), 1.0, delta=0.2)


if __name__ == "__main__":
    unittest.main()
