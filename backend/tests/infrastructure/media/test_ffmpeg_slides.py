"""Probing, capping and normalizing a multi-slide post's slides, with the real
ffmpeg/ffprobe (skipped where they are not installed, like test_ffmpeg.py)."""

import os
import shutil
import subprocess
import tempfile
import unittest

from app.domain.entities import MediaSlide, SlideKind
from app.domain.entitlements import MediaLimits, MediaTier
from app.domain.errors import MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.media import ffmpeg


def _make(path: str, *args: str) -> str:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args, path], check=True)
    return path


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg on PATH")
class SlideMediaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(temp_dir=self.temp.name)
        self.run_dir = os.path.join(self.temp.name, "run-s")
        os.makedirs(self.run_dir)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _video(self, name: str, seconds: int) -> MediaSlide:
        path = _make(
            os.path.join(self.run_dir, name),
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=duration={seconds}",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
        )
        return MediaSlide(path=path, kind=SlideKind.VIDEO)

    def _image(self, name: str, size: str = "1080x1350") -> MediaSlide:
        path = _make(os.path.join(self.run_dir, name), "-f", "lavfi", "-i", f"testsrc=size={size}", "-frames:v", "1")
        return MediaSlide(path=path, kind=SlideKind.IMAGE)

    def _limits(self, seconds: int) -> MediaLimits:
        return MediaLimits(tier=MediaTier.STANDARD, max_duration_seconds=seconds, max_file_size_mb=200)

    async def test_cap_counts_only_the_video_slides_together(self) -> None:
        slides = (self._video("slide-01.mp4", 2), self._image("slide-02.jpg"), self._video("slide-03.mp4", 3))

        total = await ffmpeg.enforce_slides_cap(self.settings, "run-s", slides, self._limits(10))

        self.assertAlmostEqual(total, 5.0, delta=0.5)

    async def test_an_all_image_post_takes_no_time(self) -> None:
        slides = (self._image("slide-01.jpg"), self._image("slide-02.png"))

        self.assertEqual(await ffmpeg.enforce_slides_cap(self.settings, "run-s", slides, self._limits(1)), 0.0)

    async def test_videos_over_the_cap_together_are_refused(self) -> None:
        slides = (self._video("slide-01.mp4", 3), self._video("slide-02.mp4", 3))

        with self.assertRaises(MediaValidationError) as caught:
            await ffmpeg.enforce_slides_cap(self.settings, "run-s", slides, self._limits(5))

        self.assertTrue(str(caught.exception).startswith("The videos in this post are 0:06 long."))

    async def test_an_image_slide_that_is_not_an_image_is_refused(self) -> None:
        # Video bytes under an image slide's name: not JPEG, PNG or WebP.
        video = self._video("clip.mp4", 1)
        fake = MediaSlide(path=os.path.join(self.run_dir, "slide-02.jpg"), kind=SlideKind.VIDEO)
        os.rename(video.path, fake.path)

        with self.assertRaises(MediaValidationError) as caught:
            await ffmpeg.enforce_slides_cap(
                self.settings, "run-s", (MediaSlide(path=fake.path, kind=SlideKind.IMAGE),), self._limits(10)
            )

        self.assertEqual(str(caught.exception), "A slide in this post couldn't be read.")

    async def test_a_manifest_posing_as_an_image_is_refused_before_ffprobe(self) -> None:
        path = os.path.join(self.run_dir, "slide-01.jpg")
        with open(path, "wb") as fh:
            fh.write(b"#EXTM3U\n#EXTINF:1,\nhttp://169.254.169.254/x.ts\n")

        with self.assertRaises(MediaValidationError):
            await ffmpeg.enforce_slides_cap(
                self.settings, "run-s", (MediaSlide(path=path, kind=SlideKind.IMAGE),), self._limits(10)
            )

    async def test_normalize_keeps_order_and_names_each_output(self) -> None:
        slides = (self._image("slide-01.png", "3000x1500"), self._video("slide-02.mp4", 1), self._image("slide-03.jpg"))

        normalized = await ffmpeg.normalize_slides(self.settings, slides, self.run_dir)

        self.assertEqual([slide.kind for slide in normalized], [SlideKind.IMAGE, SlideKind.VIDEO, SlideKind.IMAGE])
        self.assertEqual(
            [os.path.basename(slide.path) for slide in normalized],
            ["normalized-01.jpg", "normalized-02.mp4", "normalized-03.jpg"],
        )
        # A big image is brought down to the cap, keeping its shape; a small
        # one is never enlarged.
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name",
             "-of", "csv=p=0", normalized[0].path],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(probe, "mjpeg,2048,1024")
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", normalized[2].path],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(probe, "1080,1350")


if __name__ == "__main__":
    unittest.main()
