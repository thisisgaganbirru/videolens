import os
import shutil
import subprocess
import tempfile
import unittest

from app.infrastructure.config import Settings
from app.infrastructure.media.ffmpeg import _first_csv_field, _has_video_stream


class FirstCsvFieldTests(unittest.TestCase):
    def test_plain_stream(self) -> None:
        self.assertEqual(_first_csv_field(b"video\n"), b"video")

    def test_stream_with_side_data_has_a_trailing_comma(self) -> None:
        self.assertEqual(_first_csv_field(b"video,\n"), b"video")

    def test_extra_lines_after_the_stream_are_ignored(self) -> None:
        self.assertEqual(_first_csv_field(b"video,\nside data line\n"), b"video")

    def test_no_video_stream_prints_nothing(self) -> None:
        self.assertEqual(_first_csv_field(b""), b"")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg on PATH")
class HasVideoStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.settings = Settings(_env_file=None)

    def _ffmpeg(self, *args: str) -> None:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)

    async def test_video_only_file_with_side_data_is_detected_as_video(self) -> None:
        plain = os.path.join(self._dir.name, "plain.mp4")
        rotated = os.path.join(self._dir.name, "rotated.mp4")
        self._ffmpeg("-f", "lavfi", "-i", "testsrc=d=1:s=160x120", "-c:v", "libx264", plain)
        # A display-matrix rotation is stream side data, like the ambient
        # viewing block on Instagram's VP9 reels.
        self._ffmpeg("-display_rotation", "90", "-i", plain, "-c", "copy", rotated)

        self.assertTrue(await _has_video_stream(self.settings, plain))
        self.assertTrue(await _has_video_stream(self.settings, rotated))

    async def test_audio_only_file_is_not_video(self) -> None:
        audio = os.path.join(self._dir.name, "tone.mp3")
        self._ffmpeg("-f", "lavfi", "-i", "sine=d=1", audio)

        self.assertFalse(await _has_video_stream(self.settings, audio))
