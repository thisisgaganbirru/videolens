"""Per-slide pictures for a multi-slide post (thumbnails.build_slide_thumbnails
and MediaService.describe_visuals(slides=...)): numbered from 1 in order, a
failure is a null for that slide only, the set has a byte budget and a
deadline, and (against real FFmpeg) sizes, no upscaling and video frames."""

import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.domain.entities import MediaSlide, MediaVisuals, SlideKind, SlideVisual
from app.infrastructure.config import Settings
from app.infrastructure.media import thumbnails
from app.infrastructure.media.service import MediaService
from app.infrastructure.media.thumbnails import (
    MAX_SLIDE_THUMBNAIL_BYTES,
    SLIDE_MAX_SIDE,
    build_slide_thumbnails,
    slide_thumbnail,
)

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
SETTINGS = Settings(_env_file=None)

IMG = SlideKind.IMAGE
VID = SlideKind.VIDEO


def _slides(*kinds: SlideKind) -> tuple[MediaSlide, ...]:
    return tuple(
        MediaSlide(path=f"/run/slide-{i:02d}.{'jpg' if kind is IMG else 'mp4'}", kind=kind)
        for i, kind in enumerate(kinds, start=1)
    )


class BuildSlideThumbnailsTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_item_per_slide_numbered_from_one_in_order(self) -> None:
        slides = _slides(VID, IMG, IMG)
        made = AsyncMock(side_effect=[b"one", b"two", b"three"])
        with patch.object(thumbnails, "slide_thumbnail", made):
            out = await build_slide_thumbnails(SETTINGS, slides)

        self.assertEqual([(item.slide, item.kind) for item in out], [(1, VID), (2, IMG), (3, IMG)])
        self.assertEqual(
            [item.thumbnail for item in out],
            ["data:image/jpeg;base64," + base64.b64encode(b).decode() for b in (b"one", b"two", b"three")],
        )
        self.assertEqual([call.args[1] for call in made.await_args_list], list(slides))

    async def test_a_failed_slide_is_null_and_the_rest_still_come(self) -> None:
        with patch.object(thumbnails, "slide_thumbnail", AsyncMock(side_effect=[b"a", None, b"c"])):
            out = await build_slide_thumbnails(SETTINGS, _slides(IMG, IMG, IMG))
        self.assertIsNotNone(out[0].thumbnail)
        self.assertIsNone(out[1].thumbnail)
        self.assertIsNotNone(out[2].thumbnail)

    async def test_an_unexpected_error_never_escapes(self) -> None:
        with patch.object(thumbnails, "to_data_url", side_effect=RuntimeError("boom")), patch.object(
            thumbnails, "slide_thumbnail", AsyncMock(return_value=b"a")
        ), self.assertLogs("videolens", "WARNING"):
            out = await build_slide_thumbnails(SETTINGS, _slides(IMG, IMG))
        self.assertEqual(out, (SlideVisual(slide=1, kind=IMG), SlideVisual(slide=2, kind=IMG)))

    async def test_slides_past_the_byte_budget_are_null(self) -> None:
        jpeg = b"x" * 300  # 424 bytes as a data URL
        with patch.object(thumbnails, "slide_thumbnail", AsyncMock(return_value=jpeg)) as made:
            out = await build_slide_thumbnails(SETTINGS, _slides(*[IMG] * 5), budget_bytes=1000)

        self.assertEqual([item.thumbnail is not None for item in out], [True, True, False, False, False])
        self.assertEqual(len(out), 5)
        # Nothing more is made once the budget is spent.
        self.assertEqual(made.await_count, 3)

    async def test_the_deadline_leaves_the_unmade_slides_null(self) -> None:
        async def slow(settings, slide):
            if slide.path.endswith("02.jpg"):
                await asyncio.sleep(5)
            return b"a"

        with patch.object(thumbnails, "slide_thumbnail", slow):
            out = await build_slide_thumbnails(SETTINGS, _slides(IMG, IMG, IMG), deadline_seconds=0.2)

        self.assertEqual([item.thumbnail is not None for item in out], [True, False, False])

    async def test_logs_how_long_it_took_at_debug(self) -> None:
        with patch.object(thumbnails, "slide_thumbnail", AsyncMock(return_value=b"a")), self.assertLogs(
            "videolens", "DEBUG"
        ) as logs:
            await build_slide_thumbnails(SETTINGS, _slides(IMG, IMG))
        self.assertTrue(any("Slide thumbnails: 2 of 2 made" in line for line in logs.output))


class SlideThumbnailTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_video_slide_uses_the_posters_frame_rule_at_slide_size(self) -> None:
        (slide,) = _slides(VID)
        with patch.object(thumbnails, "extract_frame", AsyncMock(return_value=b"png")) as frame, patch.object(
            thumbnails, "encode_thumbnail", AsyncMock(return_value=b"jpeg")
        ) as encode:
            self.assertEqual(await slide_thumbnail(SETTINGS, slide), b"jpeg")
        # No per-slide duration: the poster's ~1s-then-0s rule.
        frame.assert_awaited_once_with(SETTINGS, slide.path, None, max_side=SLIDE_MAX_SIDE)
        self.assertEqual(encode.await_args.kwargs["max_bytes"], MAX_SLIDE_THUMBNAIL_BYTES)
        self.assertEqual(encode.await_args.kwargs["side_steps"][0], SLIDE_MAX_SIDE)

    async def test_a_video_slide_with_no_picture_is_none(self) -> None:
        with patch.object(thumbnails, "extract_frame", AsyncMock(return_value=None)), patch.object(
            thumbnails, "encode_thumbnail", AsyncMock()
        ) as encode:
            self.assertIsNone(await slide_thumbnail(SETTINGS, _slides(VID)[0]))
        encode.assert_not_awaited()

    async def test_a_missing_image_file_is_none(self) -> None:
        with self.assertLogs("videolens", "WARNING"):
            self.assertIsNone(await slide_thumbnail(SETTINGS, MediaSlide(path="/no/such.jpg", kind=IMG)))


class DescribeVisualsSlidesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = MediaService(SETTINGS)

    async def test_no_slides_means_no_slide_pictures(self) -> None:
        with patch.object(thumbnails, "probe_dimensions", AsyncMock(return_value=(1280, 720))), patch.object(
            thumbnails, "build_thumbnail", AsyncMock(return_value="data:image/jpeg;base64,P")
        ), patch.object(thumbnails, "build_slide_thumbnails", AsyncMock()) as slides:
            out = await self.service.describe_visuals(media_path="/v.mp4")
        self.assertIsNone(out.slides)
        slides.assert_not_awaited()

    async def test_slides_come_after_the_poster_and_alongside_it(self) -> None:
        order: list[str] = []
        items = (SlideVisual(slide=1, kind=IMG, thumbnail="data:image/jpeg;base64,S"),)

        async def poster(*args, **kwargs):
            order.append("poster")
            return "data:image/jpeg;base64,P"

        async def slides(*args, **kwargs):
            order.append("slides")
            return items

        with patch.object(thumbnails, "probe_dimensions", AsyncMock(return_value=(1080, 1350))), patch.object(
            thumbnails, "build_thumbnail", poster
        ), patch.object(thumbnails, "build_slide_thumbnails", slides):
            out = await self.service.describe_visuals(media_path="/s1.jpg", slides=_slides(IMG))

        self.assertEqual(order, ["poster", "slides"])
        self.assertEqual(out, MediaVisuals(thumbnail="data:image/jpeg;base64,P", width=1080, height=1350, slides=items))

    async def test_slides_that_hang_never_cost_the_poster(self) -> None:
        async def hang(*args, **kwargs):
            await asyncio.sleep(60)

        with patch.object(thumbnails, "probe_dimensions", AsyncMock(return_value=(1080, 1350))), patch.object(
            thumbnails, "build_thumbnail", AsyncMock(return_value="data:image/jpeg;base64,P")
        ), patch.object(thumbnails, "build_slide_thumbnails", hang), patch(
            "app.infrastructure.media.service.SLIDES_TIMEOUT_SECONDS", 0.1
        ), self.assertLogs("videolens", "WARNING"):
            out = await self.service.describe_visuals(media_path="/s1.jpg", slides=_slides(IMG, IMG))

        self.assertEqual(out, MediaVisuals(thumbnail="data:image/jpeg;base64,P", width=1080, height=1350))

    async def test_a_poster_that_times_out_still_leaves_the_slides(self) -> None:
        async def hang(*args, **kwargs):
            await asyncio.sleep(60)

        items = (SlideVisual(slide=1, kind=IMG, thumbnail="data:image/jpeg;base64,S"),)
        with patch.object(thumbnails, "probe_dimensions", hang), patch.object(
            thumbnails, "build_slide_thumbnails", AsyncMock(return_value=items)
        ), patch("app.infrastructure.media.service.VISUALS_TIMEOUT_SECONDS", 0.1), self.assertLogs(
            "videolens", "WARNING"
        ):
            out = await self.service.describe_visuals(media_path="/s1.jpg", slides=_slides(IMG))

        self.assertEqual(out, MediaVisuals(slides=items))


@unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg on PATH")
class RealFfmpegSlideThumbnailTests(unittest.IsolatedAsyncioTestCase):
    """Against the real binaries. Set VIDEOLENS_PRINT_THUMB_SIZES=1 to print
    the measured sizes."""

    measured: dict[str, str] = {}

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    @classmethod
    def tearDownClass(cls) -> None:
        if os.environ.get("VIDEOLENS_PRINT_THUMB_SIZES"):
            print("\nmeasured slide thumbnails:", cls.measured)

    def _path(self, name: str) -> str:
        return os.path.join(self._dir.name, name)

    def _ffmpeg(self, *args: str) -> None:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)

    def _image(self, source: str, name: str) -> str:
        path = self._path(name)
        self._ffmpeg("-f", "lavfi", "-i", source, "-frames:v", "1", "-q:v", "2", path)
        return path

    def _size(self, data_url: str) -> tuple[int, tuple[int, int]]:
        jpeg = base64.b64decode(data_url.split(",", 1)[1])
        path = self._path("probe.jpg")
        with open(path, "wb") as handle:
            handle.write(jpeg)
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_name", "-of", "csv=p=0", path],
            check=True,
            capture_output=True,
        ).stdout.decode().strip()
        codec, width, height = out.split(",")[:3]
        self.assertEqual(codec, "mjpeg")
        return len(jpeg), (int(width), int(height))

    async def test_a_mixed_post_end_to_end(self) -> None:
        detailed = self._image("mandelbrot=size=1080x1350", "s1.jpg")
        graphic = self._image("testsrc2=size=1080x1350", "s2.png")
        video = self._path("s3.mp4")
        self._ffmpeg("-f", "lavfi", "-i", "testsrc2=d=2:s=1080x1920", "-c:v", "libx264", "-pix_fmt", "yuv420p", video)
        small = self._image("testsrc2=size=300x200", "s4.jpg")
        audio_only = self._path("s5.m4a")
        self._ffmpeg("-f", "lavfi", "-i", "sine=d=1", audio_only)
        slides = (
            MediaSlide(path=detailed, kind=IMG),
            MediaSlide(path=graphic, kind=IMG),
            MediaSlide(path=video, kind=VID),
            MediaSlide(path=small, kind=IMG),
            MediaSlide(path=audio_only, kind=VID),
        )

        out = await build_slide_thumbnails(SETTINGS, slides)

        self.assertEqual([(item.slide, item.kind) for item in out], [(i, s.kind) for i, s in enumerate(slides, 1)])
        sizes = {}
        for item, name in zip(out[:4], ("photo_like_1080x1350", "graphic_1080x1350", "video_1080x1920", "small_300x200")):
            sizes[name] = self._size(item.thumbnail)
        self.measured.update({k: f"{v[0]} B {v[1][0]}x{v[1][1]}" for k, v in sizes.items()})
        # A 1080x1350 slide becomes 384x480 at ~25-60 KB (the detailed one).
        self.assertEqual(sizes["photo_like_1080x1350"][1], (384, 480))
        self.assertGreater(sizes["photo_like_1080x1350"][0], 15 * 1024)
        self.assertLessEqual(sizes["photo_like_1080x1350"][0], 60 * 1024)
        self.assertEqual(sizes["graphic_1080x1350"][1], (384, 480))
        # A video slide: a frame, portrait as shot.
        self.assertEqual(sizes["video_1080x1920"][1], (270, 480))
        # Never enlarged.
        self.assertEqual(sizes["small_300x200"][1], (300, 200))
        # A "video" slide with no picture has nothing to show.
        self.assertIsNone(out[4].thumbnail)
        for item in out[:4]:
            self.assertLessEqual(self._size(item.thumbnail)[0], MAX_SLIDE_THUMBNAIL_BYTES)

    async def test_pure_noise_still_fits_the_per_slide_ceiling(self) -> None:
        noisy = self._image("nullsrc=s=1080x1350,geq=random(1)*255:128:128", "noise.png")
        jpeg = await slide_thumbnail(SETTINGS, MediaSlide(path=noisy, kind=IMG))
        self.assertIsNotNone(jpeg)
        self.measured["noise_1080x1350"] = f"{len(jpeg)} B"
        self.assertLessEqual(len(jpeg), MAX_SLIDE_THUMBNAIL_BYTES)


if __name__ == "__main__":
    unittest.main()
