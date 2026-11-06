import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.domain.entities import MediaVisuals
from app.infrastructure.config import Settings
from app.infrastructure.media import thumbnails
from app.infrastructure.media.service import MediaService
from app.infrastructure.media.thumbnails import (
    MAX_SIDE,
    MAX_THUMBNAIL_BYTES,
    _fetch_image_sync,
    build_thumbnail,
    dimensions_from_info,
    encode_thumbnail,
    extract_frame,
    frame_offset_seconds,
    parse_video_dimensions,
    probe_dimensions,
    thumbnail_urls_from_info,
)

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _probe_json(stream: dict | None) -> bytes:
    return json.dumps({"streams": [stream] if stream else []}).encode()


class ThumbnailUrlsFromInfoTests(unittest.TestCase):
    def test_chosen_thumbnail_first_then_largest_preferred_entry(self) -> None:
        info = {
            "thumbnail": "https://i.ytimg.com/vi/x/maxres.jpg",
            "thumbnails": [
                {"url": "https://i.ytimg.com/vi/x/small.jpg", "width": 120, "height": 90, "preference": -10},
                {"url": "https://i.ytimg.com/vi/x/hq.jpg", "width": 480, "height": 360, "preference": -1},
                {"url": "https://i.ytimg.com/vi/x/maxres.jpg", "preference": 0},
            ],
        }
        self.assertEqual(
            thumbnail_urls_from_info(info),
            ("https://i.ytimg.com/vi/x/maxres.jpg", "https://i.ytimg.com/vi/x/hq.jpg"),
        )

    def test_entries_without_preference_rank_by_area(self) -> None:
        info = {
            "thumbnails": [
                {"url": "https://cdn.test/a.jpg", "width": 100, "height": 100},
                {"url": "https://cdn.test/b.jpg", "width": 640, "height": 640},
            ]
        }
        self.assertEqual(thumbnail_urls_from_info(info)[0], "https://cdn.test/b.jpg")

    def test_non_http_urls_and_junk_are_ignored(self) -> None:
        info = {"thumbnail": "file:///etc/passwd", "thumbnails": [None, {"url": 3}, {"url": "data:x"}]}
        self.assertEqual(thumbnail_urls_from_info(info), ())

    def test_nothing_is_empty(self) -> None:
        self.assertEqual(thumbnail_urls_from_info({}), ())


class DimensionsFromInfoTests(unittest.TestCase):
    def test_both_positive(self) -> None:
        self.assertEqual(dimensions_from_info({"width": 1080, "height": 1920}), (1080, 1920))

    def test_missing_or_zero_is_none_for_both(self) -> None:
        self.assertEqual(dimensions_from_info({"width": 1080}), (None, None))
        self.assertEqual(dimensions_from_info({"width": 0, "height": 10}), (None, None))
        self.assertEqual(dimensions_from_info({"width": "x", "height": 10}), (None, None))


class ParseVideoDimensionsTests(unittest.TestCase):
    def test_plain_landscape(self) -> None:
        self.assertEqual(parse_video_dimensions(_probe_json({"width": 1280, "height": 720})), (1280, 720))

    def test_display_matrix_rotation_swaps(self) -> None:
        for rotation in (90, -90, 270, -270):
            with self.subTest(rotation=rotation):
                payload = _probe_json(
                    {"width": 1920, "height": 1080, "side_data_list": [{"rotation": rotation}]}
                )
                self.assertEqual(parse_video_dimensions(payload), (1080, 1920))

    def test_legacy_rotate_tag_swaps(self) -> None:
        payload = _probe_json({"width": 1920, "height": 1080, "tags": {"rotate": "90"}})
        self.assertEqual(parse_video_dimensions(payload), (1080, 1920))

    def test_half_turn_does_not_swap(self) -> None:
        payload = _probe_json({"width": 1920, "height": 1080, "side_data_list": [{"rotation": 180}]})
        self.assertEqual(parse_video_dimensions(payload), (1920, 1080))

    def test_side_data_without_rotation_is_ignored(self) -> None:
        payload = _probe_json(
            {"width": 1920, "height": 1080, "side_data_list": [{"side_data_type": "Ambient viewing"}]}
        )
        self.assertEqual(parse_video_dimensions(payload), (1920, 1080))

    def test_cover_art_is_not_video(self) -> None:
        payload = _probe_json({"width": 500, "height": 500, "disposition": {"attached_pic": 1}})
        self.assertIsNone(parse_video_dimensions(payload))

    def test_no_stream_or_garbage_is_none(self) -> None:
        self.assertIsNone(parse_video_dimensions(_probe_json(None)))
        self.assertIsNone(parse_video_dimensions(b"not json"))
        self.assertIsNone(parse_video_dimensions(b""))
        self.assertIsNone(parse_video_dimensions(_probe_json({"width": 0, "height": 720})))


class FrameOffsetTests(unittest.TestCase):
    def test_one_second_in_unless_the_clip_is_short(self) -> None:
        self.assertEqual(frame_offset_seconds(None), 1.0)
        self.assertEqual(frame_offset_seconds(120.0), 1.0)
        self.assertAlmostEqual(frame_offset_seconds(4.0), 0.4)
        self.assertEqual(frame_offset_seconds(0), 1.0)


class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, length: str | None = None) -> None:
        super().__init__(body)
        self.headers = {"Content-Length": length} if length is not None else {}


class _FakeOpener:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.opened: list[str] = []

    def open(self, request, timeout=None):
        self.opened.append(request.full_url)
        return self._response


class FetchImageTests(unittest.TestCase):
    def _fetch(self, response: _FakeResponse, max_bytes: int = 10) -> bytes:
        with patch.object(thumbnails, "validate_public_url"), patch.object(
            thumbnails.urllib.request, "build_opener", return_value=_FakeOpener(response)
        ):
            return _fetch_image_sync("https://cdn.test/t.jpg", max_bytes, 1)

    def test_returns_the_body_within_the_cap(self) -> None:
        self.assertEqual(self._fetch(_FakeResponse(b"12345")), b"12345")

    def test_declared_length_over_the_cap_is_refused_before_reading(self) -> None:
        with self.assertRaises(ValueError):
            self._fetch(_FakeResponse(b"1", length="11"))

    def test_body_over_the_cap_is_refused_even_without_a_length(self) -> None:
        with self.assertRaises(ValueError):
            self._fetch(_FakeResponse(b"x" * 11))

    def test_empty_body_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._fetch(_FakeResponse(b""))

    def test_private_address_is_refused_by_the_ssrf_guard(self) -> None:
        with patch.object(
            thumbnails.urllib.request, "build_opener", side_effect=AssertionError("must not open")
        ):
            with self.assertRaises(Exception) as caught:
                _fetch_image_sync("http://127.0.0.1/t.jpg", 10, 1)
        self.assertNotIsInstance(caught.exception, AssertionError)

    def test_redirects_go_through_the_validating_handler(self) -> None:
        with patch.object(thumbnails, "validate_public_url"), patch.object(
            thumbnails.urllib.request, "build_opener", return_value=_FakeOpener(_FakeResponse(b"1"))
        ) as build:
            _fetch_image_sync("https://cdn.test/t.jpg", 10, 1)
        build.assert_called_once_with(thumbnails.ValidatingRedirectHandler)

    def test_async_wrapper_turns_failures_into_none(self) -> None:
        result = asyncio.run(thumbnails.fetch_image("http://127.0.0.1/t.jpg"))
        self.assertIsNone(result)


class EncodeCeilingTests(unittest.IsolatedAsyncioTestCase):
    """The quality/size stepping, with ffmpeg replaced by a size table."""

    async def test_steps_quality_then_size_until_under_the_ceiling(self) -> None:
        calls: list[tuple[str, str]] = []

        async def fake_run(command, stdin=None):
            side = command[command.index("-vf") + 1].split("min(")[1].split(",")[0]
            quality = command[command.index("-q:v") + 1]
            calls.append((side, quality))
            fits = side == "240" and quality == "16"
            return 0, b"j" * (MAX_THUMBNAIL_BYTES if fits else MAX_THUMBNAIL_BYTES + 1)

        with patch.object(thumbnails, "_run", fake_run), patch.object(
            thumbnails, "_media_binary", return_value="ffmpeg"
        ):
            out = await encode_thumbnail(Settings(_env_file=None), b"img")

        self.assertEqual(len(out), MAX_THUMBNAIL_BYTES)
        # Every quality at 320 first, then down the 240 ladder to the fit.
        self.assertEqual([c for c in calls if c[0] == "320"], [("320", q) for q in ("4", "7", "11", "16", "23", "31")])
        self.assertEqual(calls[-1], ("240", "16"))

    async def test_never_fitting_is_none(self) -> None:
        async def fake_run(command, stdin=None):
            return 0, b"j" * (MAX_THUMBNAIL_BYTES + 1)

        with patch.object(thumbnails, "_run", fake_run), patch.object(
            thumbnails, "_media_binary", return_value="ffmpeg"
        ):
            self.assertIsNone(await encode_thumbnail(Settings(_env_file=None), b"img"))

    async def test_unreadable_input_stops_after_one_attempt(self) -> None:
        run = AsyncMock(return_value=(1, b""))
        with patch.object(thumbnails, "_run", run), patch.object(
            thumbnails, "_media_binary", return_value="ffmpeg"
        ):
            self.assertIsNone(await encode_thumbnail(Settings(_env_file=None), b"not an image"))
        self.assertEqual(run.await_count, 1)


class BuildThumbnailFallbackTests(unittest.IsolatedAsyncioTestCase):
    """Order of sources, with fetch/encode/extract mocked."""

    def setUp(self) -> None:
        self.settings = Settings(_env_file=None)

    async def test_publisher_thumbnail_wins(self) -> None:
        with patch.object(thumbnails, "fetch_image", AsyncMock(return_value=b"img")), patch.object(
            thumbnails, "encode_thumbnail", AsyncMock(return_value=b"jpeg")
        ), patch.object(thumbnails, "extract_frame", AsyncMock()) as frame:
            out = await build_thumbnail(
                self.settings, thumbnail_urls=("https://a",), media_path="/m.mp4", has_video=True
            )
        self.assertEqual(out, "data:image/jpeg;base64," + base64.b64encode(b"jpeg").decode())
        frame.assert_not_awaited()

    async def test_second_url_tried_when_the_first_fetch_fails(self) -> None:
        fetch = AsyncMock(side_effect=[None, b"img"])
        with patch.object(thumbnails, "fetch_image", fetch), patch.object(
            thumbnails, "encode_thumbnail", AsyncMock(return_value=b"jpeg")
        ):
            out = await build_thumbnail(self.settings, thumbnail_urls=("https://a", "https://b"))
        self.assertIsNotNone(out)
        self.assertEqual(fetch.await_count, 2)

    async def test_frame_fallback_when_the_fetch_fails(self) -> None:
        with patch.object(thumbnails, "fetch_image", AsyncMock(return_value=None)), patch.object(
            thumbnails, "extract_frame", AsyncMock(return_value=b"png")
        ) as frame, patch.object(thumbnails, "encode_thumbnail", AsyncMock(return_value=b"jpeg")):
            out = await build_thumbnail(
                self.settings,
                thumbnail_urls=("https://a",),
                media_path="/m.mp4",
                has_video=True,
                duration_seconds=30.0,
            )
        self.assertIsNotNone(out)
        frame.assert_awaited_once_with(self.settings, "/m.mp4", 30.0)

    async def test_frame_fallback_when_the_transcode_fails(self) -> None:
        encode = AsyncMock(side_effect=[None, b"jpeg"])
        with patch.object(thumbnails, "fetch_image", AsyncMock(return_value=b"html")), patch.object(
            thumbnails, "extract_frame", AsyncMock(return_value=b"png")
        ), patch.object(thumbnails, "encode_thumbnail", encode):
            out = await build_thumbnail(
                self.settings, thumbnail_urls=("https://a",), media_path="/m.mp4", has_video=True
            )
        self.assertIsNotNone(out)

    async def test_frame_fallback_when_there_is_no_thumbnail_url(self) -> None:
        with patch.object(thumbnails, "extract_frame", AsyncMock(return_value=b"png")), patch.object(
            thumbnails, "encode_thumbnail", AsyncMock(return_value=b"jpeg")
        ):
            out = await build_thumbnail(self.settings, media_path="/m.mp4", has_video=True)
        self.assertIsNotNone(out)

    async def test_audio_gets_no_frame_grab(self) -> None:
        with patch.object(thumbnails, "extract_frame", AsyncMock()) as frame:
            out = await build_thumbnail(self.settings, media_path="/a.mp3", has_video=False)
        self.assertIsNone(out)
        frame.assert_not_awaited()

    async def test_captions_path_with_a_failing_fetch_is_none(self) -> None:
        with patch.object(thumbnails, "fetch_image", AsyncMock(return_value=None)):
            self.assertIsNone(await build_thumbnail(self.settings, thumbnail_urls=("https://a",)))

    async def test_unexpected_errors_are_swallowed(self) -> None:
        with patch.object(thumbnails, "fetch_image", AsyncMock(side_effect=RuntimeError("boom"))):
            self.assertIsNone(await build_thumbnail(self.settings, thumbnail_urls=("https://a",)))


class DescribeVisualsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = MediaService(Settings(_env_file=None))

    async def test_probed_dimensions_win_over_yt_dlp_hints(self) -> None:
        with patch.object(thumbnails, "probe_dimensions", AsyncMock(return_value=(1080, 1920))), patch.object(
            thumbnails, "build_thumbnail", AsyncMock(return_value="data:x")
        ) as build:
            out = await self.service.describe_visuals(
                media_path="/m.mp4", thumbnail_urls=("https://a",), width=1920, height=1080
            )
        self.assertEqual(out, MediaVisuals(thumbnail="data:x", width=1080, height=1920))
        self.assertTrue(build.await_args.kwargs["has_video"])

    async def test_captions_path_uses_the_hints(self) -> None:
        with patch.object(thumbnails, "probe_dimensions", AsyncMock()) as probe, patch.object(
            thumbnails, "build_thumbnail", AsyncMock(return_value=None)
        ):
            out = await self.service.describe_visuals(thumbnail_urls=("https://a",), width=1280, height=720)
        probe.assert_not_awaited()
        self.assertEqual(out, MediaVisuals(thumbnail=None, width=1280, height=720))

    async def test_audio_upload_is_all_none(self) -> None:
        with patch.object(thumbnails, "probe_dimensions", AsyncMock(return_value=None)), patch.object(
            thumbnails, "build_thumbnail", AsyncMock(return_value=None)
        ) as build:
            out = await self.service.describe_visuals(media_path="/a.mp3")
        self.assertEqual(out, MediaVisuals())
        self.assertFalse(build.await_args.kwargs["has_video"])

    async def test_never_raises(self) -> None:
        with patch.object(thumbnails, "probe_dimensions", AsyncMock(side_effect=RuntimeError("x"))):
            self.assertEqual(await self.service.describe_visuals(media_path="/m.mp4"), MediaVisuals())


@unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg on PATH")
class RealFfmpegThumbnailTests(unittest.IsolatedAsyncioTestCase):
    """End to end against the real binaries: sizes, aspect, rotation."""

    # Filled by the tests, printed at teardown so a run shows real sizes.
    measured: dict[str, int] = {}

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.settings = Settings(_env_file=None)

    @classmethod
    def tearDownClass(cls) -> None:
        if os.environ.get("VIDEOLENS_PRINT_THUMB_SIZES"):
            print("\nmeasured thumbnail sizes:", cls.measured)

    def _path(self, name: str) -> str:
        return os.path.join(self._dir.name, name)

    def _ffmpeg(self, *args: str) -> None:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)

    def _image(self, source: str, name: str) -> bytes:
        path = self._path(name)
        self._ffmpeg("-f", "lavfi", "-i", source, "-frames:v", "1", path)
        with open(path, "rb") as handle:
            return handle.read()

    def _jpeg_size(self, data_url: str) -> tuple[bytes, tuple[int, int]]:
        jpeg = base64.b64decode(data_url.split(",", 1)[1])
        path = self._path("out.jpg")
        with open(path, "wb") as handle:
            handle.write(jpeg)
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
            check=True,
            capture_output=True,
        ).stdout.decode().strip()
        width, height = (int(v) for v in out.split(",")[:2])
        return jpeg, (width, height)

    async def test_landscape_poster_is_capped_and_keeps_its_aspect(self) -> None:
        image = self._image("testsrc2=s=1280x720", "poster.png")
        with patch.object(thumbnails, "fetch_image", AsyncMock(return_value=image)):
            out = await build_thumbnail(self.settings, thumbnail_urls=("https://a",))
        jpeg, (width, height) = self._jpeg_size(out)
        self.measured["poster_1280x720"] = len(jpeg)
        self.assertLessEqual(len(jpeg), MAX_THUMBNAIL_BYTES)
        self.assertEqual((width, height), (320, 180))

    async def test_noisy_image_still_lands_under_the_ceiling(self) -> None:
        # Pure noise is close to the worst case for JPEG.
        image = self._image("nullsrc=s=1920x1080,geq=random(1)*255:128:128", "noise.png")
        jpeg_bytes = await encode_thumbnail(self.settings, image)
        self.assertIsNotNone(jpeg_bytes)
        self.measured["noise_1920x1080"] = len(jpeg_bytes)
        self.assertLessEqual(len(jpeg_bytes), MAX_THUMBNAIL_BYTES)

    async def test_small_images_are_not_enlarged(self) -> None:
        image = self._image("testsrc2=s=160x90", "small.png")
        out = await build_thumbnail(self.settings, thumbnail_urls=())  # no source at all
        self.assertIsNone(out)
        jpeg = await encode_thumbnail(self.settings, image)
        _, size = self._jpeg_size("data:," + base64.b64encode(jpeg).decode())
        self.assertEqual(size, (160, 90))

    async def test_rotated_phone_video_is_portrait_in_dims_and_frame(self) -> None:
        plain, rotated = self._path("plain.mp4"), self._path("rotated.mp4")
        self._ffmpeg("-f", "lavfi", "-i", "testsrc2=d=2:s=1280x720", "-c:v", "libx264", plain)
        self._ffmpeg("-display_rotation", "90", "-i", plain, "-c", "copy", rotated)

        self.assertEqual(await probe_dimensions(self.settings, plain), (1280, 720))
        self.assertEqual(await probe_dimensions(self.settings, rotated), (720, 1280))

        visuals = await MediaService(self.settings).describe_visuals(
            media_path=rotated, duration_seconds=2.0
        )
        self.assertEqual((visuals.width, visuals.height), (720, 1280))
        jpeg, (width, height) = self._jpeg_size(visuals.thumbnail)
        self.measured["frame_rotated_720x1280"] = len(jpeg)
        self.assertLessEqual(len(jpeg), MAX_THUMBNAIL_BYTES)
        self.assertEqual((width, height), (180, 320))
        self.assertLessEqual(max(width, height), MAX_SIDE)

    async def test_fetched_garbage_falls_back_to_a_frame(self) -> None:
        video = self._path("v.mp4")
        self._ffmpeg("-f", "lavfi", "-i", "testsrc2=d=1:s=640x360", "-c:v", "libx264", video)
        with patch.object(thumbnails, "fetch_image", AsyncMock(return_value=b"<html>nope</html>")):
            visuals = await MediaService(self.settings).describe_visuals(
                media_path=video, thumbnail_urls=("https://a",)
            )
        self.assertIsNotNone(visuals.thumbnail)
        self.assertEqual((visuals.width, visuals.height), (640, 360))

    async def test_audio_has_no_dims_and_no_thumbnail(self) -> None:
        audio = self._path("tone.mp3")
        self._ffmpeg("-f", "lavfi", "-i", "sine=d=1", audio)
        self.assertEqual(await MediaService(self.settings).describe_visuals(media_path=audio), MediaVisuals())

    async def test_frame_seek_past_the_end_retries_at_zero(self) -> None:
        video = self._path("short.mp4")
        self._ffmpeg("-f", "lavfi", "-i", "testsrc2=d=0.3:s=320x240", "-c:v", "libx264", video)
        # Claim a long duration so the first seek (1s) lands past the end.
        frame = await extract_frame(self.settings, video, 60.0)
        self.assertIsNotNone(frame)


if __name__ == "__main__":
    unittest.main()
