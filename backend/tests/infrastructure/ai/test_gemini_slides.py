"""A multi-slide post in one Gemini request (`analyze_slides_with_retry`),
with the same fake client as test_gemini_engine.py."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import errors as genai_errors
from google.genai import types

from app.domain.entities import (
    AnalysisContext,
    MediaSlide,
    ScreenTextSegment,
    SlideKind,
    TranscriptSegment,
    VideoAnalysis,
)
from app.infrastructure.ai.gemini_engine import CAROUSEL_SYSTEM_INSTRUCTION, SYSTEM_INSTRUCTION, GeminiEngine
from app.infrastructure.config import Settings
from tests.infrastructure.ai.test_gemini_engine import _RESULT, _FakeClient, _api_error, _busy, _engine

_SLIDES = (
    MediaSlide(path="normalized-01.jpg", kind=SlideKind.IMAGE),
    MediaSlide(path="normalized-02.mp4", kind=SlideKind.VIDEO),
    MediaSlide(path="normalized-03.jpg", kind=SlideKind.IMAGE),
)


def _with_slides(*slides) -> VideoAnalysis:
    return VideoAnalysis(
        title="t",
        summary="s",
        transcript="tr",
        transcript_segments=[TranscriptSegment(start_seconds=1, end_seconds=2, text="hi", slide=slides[0])],
        screen_text="x",
        screen_text_segments=[
            ScreenTextSegment(start_seconds=0, end_seconds=0, text=f"text {n}", slide=n) for n in slides
        ],
        markdown="# m",
    )


def _file_name(part) -> str | None:
    """The upload a content part stands for: the file itself, or an image
    slide's Part wrapping its uri."""
    if isinstance(part, types.Part):
        return part.file_data.file_uri.removeprefix("https://files.test/")
    return getattr(part, "name", None)


def _media(contents) -> list:
    return [part for part in contents if not isinstance(part, str)]


class _ConfigSpy(_FakeClient):
    """Also keeps each request's config, for the system instruction."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.configs: list[types.GenerateContentConfig] = []
        generate = self.models.generate_content

        async def spy(model, contents, config):
            self.configs.append(config)
            return await generate(model, contents, config)

        self.models.generate_content = spy


class AnalyzeSlidesTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_slide_is_one_labelled_part_of_one_request(self) -> None:
        client = _ConfigSpy([_RESULT])
        engine, _ = _engine(client)

        result = await engine.analyze_slides_with_retry(_SLIDES)

        # Nothing to rebuild (no segments), so the model's result comes back as is.
        self.assertIs(result, _RESULT)
        self.assertEqual(client.files.upload_calls, 3)
        (contents,) = client.models.contents_seen
        labels = [part for part in contents if isinstance(part, str)]
        self.assertEqual(
            labels[:3], ["Slide 1 of 3 (image):", "Slide 2 of 3 (video):", "Slide 3 of 3 (image):"]
        )
        self.assertEqual(labels[3], "Analyze this 3-slide post as instructed.")
        # Each label sits right before its own upload, media before any prompt text.
        self.assertEqual([_file_name(part) for part in contents[1:6:2]], ["files/1", "files/2", "files/3"])
        self.assertEqual(client.configs[0].system_instruction, CAROUSEL_SYSTEM_INSTRUCTION)
        await engine.drain()
        self.assertEqual(sorted(client.files.deleted), ["files/1", "files/2", "files/3"])

    async def test_slide_numbers_outside_the_post_are_cleared(self) -> None:
        client = _FakeClient([_with_slides(2, 0, 3, 9)])
        engine, _ = _engine(client)

        result = await engine.analyze_slides_with_retry(_SLIDES)

        self.assertEqual(result.transcript_segments[0].slide, 2)
        self.assertEqual([segment.slide for segment in result.screen_text_segments], [2, None, 3, None])

    async def test_a_single_file_never_keeps_a_slide_number(self) -> None:
        client = _ConfigSpy([_with_slides(1)])
        engine, _ = _engine(client)

        result = await engine.analyze_with_retry("clip.mp4")

        self.assertIsNone(result.transcript_segments[0].slide)
        self.assertIsNone(result.screen_text_segments[0].slide)
        self.assertEqual(client.configs[0].system_instruction, SYSTEM_INSTRUCTION)
        self.assertEqual([part for part in client.models.contents_seen[0] if isinstance(part, str)],
                         ["Analyze this media file as instructed."])

    async def test_a_slide_gemini_could_not_process_reuploads_the_post(self) -> None:
        # Slide 2 of the first attempt FAILS; the second attempt is all ACTIVE.
        client = _FakeClient([_RESULT], states=[types.FileState.ACTIVE, types.FileState.FAILED])
        engine, _ = _engine(client)

        result = await engine.analyze_slides_with_retry(_SLIDES)

        self.assertIs(result, _RESULT)
        # First attempt: slides 1 and 2 (no new upload starts after the
        # failure); second attempt: all three. Every upload is deleted.
        self.assertEqual(client.files.upload_calls, 5)
        await engine.drain()
        self.assertEqual(len(client.files.deleted), 5)

    async def test_an_upload_that_fails_still_deletes_the_slides_before_it(self) -> None:
        bad = _api_error(genai_errors.ClientError, 400, "Unsupported file.")
        client = _FakeClient([_RESULT], upload_outcomes=[None, bad])
        engine, _ = _engine(client)

        with self.assertRaises(genai_errors.ClientError):
            await engine.analyze_slides_with_retry(_SLIDES)

        await engine.drain()
        self.assertEqual(client.files.deleted, ["files/1"])
        self.assertEqual(client.models.contents_seen, [])


class SlideImageResolutionTests(unittest.IsolatedAsyncioTestCase):
    """Small print on an image slide (a terminal block under a headline) was
    dropped at the model's default image resolution, so image slides ask for
    more per part; video slides and single files are left alone."""

    async def test_only_image_slides_carry_a_media_resolution(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client)

        await engine.analyze_slides_with_retry(_SLIDES)

        media = _media(client.models.contents_seen[0])
        self.assertIsInstance(media[0], types.Part)
        self.assertEqual(media[0].media_resolution.level, types.PartMediaResolutionLevel.MEDIA_RESOLUTION_HIGH)
        self.assertEqual(media[0].file_data.file_uri, "https://files.test/files/1")
        self.assertEqual(media[0].file_data.mime_type, "application/octet-stream")
        # The video slide is the upload itself, as before.
        self.assertNotIsInstance(media[1], types.Part)
        self.assertEqual(media[1].name, "files/2")
        self.assertIsInstance(media[2], types.Part)

    async def test_the_level_follows_the_setting_and_blank_leaves_it_to_the_model(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, gemini_slide_image_resolution="ultra_high")
        await engine.analyze_slides_with_retry(_SLIDES)
        self.assertEqual(
            _media(client.models.contents_seen[0])[0].media_resolution.level,
            types.PartMediaResolutionLevel.MEDIA_RESOLUTION_ULTRA_HIGH,
        )

        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, gemini_slide_image_resolution="")
        await engine.analyze_slides_with_retry(_SLIDES)
        self.assertFalse(any(isinstance(part, types.Part) for part in client.models.contents_seen[0]))

    async def test_a_single_file_is_never_wrapped(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client)

        await engine.analyze_with_retry("photo.jpg")

        self.assertFalse(any(isinstance(part, types.Part) for part in client.models.contents_seen[0]))

    def test_an_unknown_level_is_refused_by_the_settings(self) -> None:
        with self.assertRaises(ValueError):
            Settings(gemini_slide_image_resolution="huge")


class SlideVideoSamplingTests(unittest.IsolatedAsyncioTestCase):
    """GEMINI_VIDEO_FPS and GEMINI_MEDIA_RESOLUTION on a multi-slide post:
    both reach its video slides, per part; image slides keep only their own
    GEMINI_SLIDE_IMAGE_RESOLUTION, and the request never carries a
    request-wide media_resolution next to per-part ones."""

    async def test_unset_leaves_the_post_exactly_as_before(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client)

        await engine.analyze_slides_with_retry(_SLIDES)

        media = _media(client.models.contents_seen[0])
        self.assertNotIsInstance(media[1], types.Part)  # the video slide, unwrapped
        self.assertIsNone(media[0].video_metadata)
        self.assertIsNone(client.models.configs_seen[0].media_resolution)

    async def test_fps_reaches_video_slides_only(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, gemini_video_fps=2.0)

        await engine.analyze_slides_with_retry(_SLIDES)

        image, video, last = _media(client.models.contents_seen[0])
        self.assertIsInstance(video, types.Part)
        self.assertEqual(video.file_data.file_uri, "https://files.test/files/2")
        self.assertEqual(video.file_data.mime_type, "video/mp4")
        self.assertEqual(video.video_metadata.fps, 2.0)
        self.assertIsNone(video.media_resolution)
        for part in (image, last):
            self.assertIsNone(part.video_metadata)
            self.assertEqual(part.media_resolution.level, types.PartMediaResolutionLevel.MEDIA_RESOLUTION_HIGH)

    async def test_media_resolution_goes_per_part_on_video_slides_never_request_wide(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(
            client,
            gemini_media_resolution="low",
            gemini_slide_image_resolution="ultra_high",
            gemini_video_fps=2.0,
        )

        await engine.analyze_slides_with_retry(_SLIDES)

        image, video, _ = _media(client.models.contents_seen[0])
        self.assertIsNone(client.models.configs_seen[0].media_resolution)
        # Per part wins for an image slide: its own setting, not the video one.
        self.assertEqual(image.media_resolution.level, types.PartMediaResolutionLevel.MEDIA_RESOLUTION_ULTRA_HIGH)
        self.assertEqual(video.media_resolution.level, types.PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW)
        self.assertEqual(video.video_metadata.fps, 2.0)

    async def test_a_blank_image_level_does_not_inherit_the_video_one(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, gemini_media_resolution="high", gemini_slide_image_resolution="")

        await engine.analyze_slides_with_retry(_SLIDES)

        image, video, last = _media(client.models.contents_seen[0])
        self.assertNotIsInstance(image, types.Part)
        self.assertNotIsInstance(last, types.Part)
        self.assertEqual(video.media_resolution.level, types.PartMediaResolutionLevel.MEDIA_RESOLUTION_HIGH)
        self.assertIsNone(client.models.configs_seen[0].media_resolution)


class SlideTokenBudgetTests(unittest.IsolatedAsyncioTestCase):
    """GEMINI_VIDEO_TOKEN_BUDGET on a mixed image + video post. The
    estimate is the video slides' total length (`AnalysisContext`); over the
    budget only the video slides go back to defaults, and image slides keep
    GEMINI_SLIDE_IMAGE_RESOLUTION either way."""

    _SETTINGS = {
        "gemini_video_fps": 2.0,
        "gemini_media_resolution": "high",
        "gemini_slide_image_resolution": "ultra_high",
    }

    def _assert_images_keep_their_level(self, image, last) -> None:
        for part in (image, last):
            self.assertIsNone(part.video_metadata)
            self.assertEqual(part.media_resolution.level, types.PartMediaResolutionLevel.MEDIA_RESOLUTION_ULTRA_HIGH)

    async def test_over_budget_resets_the_video_slides_only(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, gemini_video_token_budget=100_000, **self._SETTINGS)

        with self.assertLogs("app.infrastructure.ai.gemini_engine", "INFO") as logs:
            await engine.analyze_slides_with_retry(
                _SLIDES, context=AnalysisContext(run_id="run-1", duration_seconds=600.0)
            )

        image, video, last = _media(client.models.contents_seen[0])
        self.assertNotIsInstance(video, types.Part)  # the bare upload: no fps, no level
        self._assert_images_keep_their_level(image, last)
        self.assertIsNone(client.models.configs_seen[0].media_resolution)
        (line,) = [line for line in logs.output if "Gemini usage" in line]
        self.assertIn("op=slides", line)
        self.assertIn("slides=3", line)
        self.assertIn("estimated_video_tokens=351000", line)
        self.assertIn("budget_downgraded=true", line)

    async def test_under_budget_keeps_fps_and_resolution_on_the_video_slides(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, **self._SETTINGS)

        await engine.analyze_slides_with_retry(_SLIDES, context=AnalysisContext(duration_seconds=30.0))

        image, video, last = _media(client.models.contents_seen[0])
        self.assertEqual(video.video_metadata.fps, 2.0)
        self.assertEqual(video.media_resolution.level, types.PartMediaResolutionLevel.MEDIA_RESOLUTION_HIGH)
        self._assert_images_keep_their_level(image, last)
        self.assertIsNone(client.models.configs_seen[0].media_resolution)

    async def test_a_post_of_images_only_is_never_estimated(self) -> None:
        images = (
            MediaSlide(path="normalized-01.jpg", kind=SlideKind.IMAGE),
            MediaSlide(path="normalized-02.jpg", kind=SlideKind.IMAGE),
        )
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, gemini_video_token_budget=1, **self._SETTINGS)

        with self.assertLogs("app.infrastructure.ai.gemini_engine", "INFO") as logs:
            await engine.analyze_slides_with_retry(images, context=AnalysisContext(duration_seconds=600.0))

        self._assert_images_keep_their_level(*_media(client.models.contents_seen[0]))
        (line,) = [line for line in logs.output if "Gemini usage" in line]
        self.assertIn("estimated_video_tokens=null", line)
        self.assertIn("budget_downgraded=false", line)

    async def test_an_older_fallback_gets_no_per_part_level_on_any_slide(self) -> None:
        client = _FakeClient([_busy(), _RESULT])
        engine, _ = _engine(
            client, gemini_retry_attempts=1, gemini_fallback_model="gemini-2.5-flash", **self._SETTINGS
        )

        await engine.analyze_slides_with_retry(_SLIDES)

        primary = _media(client.models.contents_seen[0])
        fallback = _media(client.models.contents_seen[1])
        self.assertEqual(primary[0].media_resolution.level, types.PartMediaResolutionLevel.MEDIA_RESOLUTION_ULTRA_HIGH)
        for part in fallback:
            self.assertIsNone(part.media_resolution)
        self.assertEqual(fallback[1].video_metadata.fps, 2.0)
        self.assertEqual([_file_name(part) for part in fallback], ["files/1", "files/2", "files/3"])


class SlideScreenTextTests(unittest.IsolatedAsyncioTestCase):
    """The flat screen_text of a post is rebuilt from its segments, so it
    carries every slide's full text; a video keeps the model's own."""

    _FULL = VideoAnalysis(
        title="t",
        summary="s",
        transcript="",
        screen_text="Headline one",
        screen_text_segments=[
            ScreenTextSegment(start_seconds=0, end_seconds=0, text="Headline one\nsubtitle\n$ npm run build\n> done", slide=1),
            ScreenTextSegment(start_seconds=0, end_seconds=0, text="  ", slide=2),
            ScreenTextSegment(start_seconds=0, end_seconds=0, text="Headline three\n$ ls -la", slide=3),
        ],
        markdown="# m",
    )

    async def test_slide_screen_text_is_every_segment_in_order(self) -> None:
        client = _FakeClient([self._FULL])
        engine, _ = _engine(client)

        result = await engine.analyze_slides_with_retry(_SLIDES)

        self.assertEqual(
            result.screen_text,
            "Headline one\nsubtitle\n$ npm run build\n> done\n\nHeadline three\n$ ls -la",
        )
        # The segments themselves, slide numbers and timestamps are untouched.
        self.assertEqual(result.screen_text_segments, self._FULL.screen_text_segments)

    async def test_no_segment_text_keeps_the_models_screen_text(self) -> None:
        empty = self._FULL.model_copy(update={"screen_text": "kept", "screen_text_segments": []})
        client = _FakeClient([empty])
        engine, _ = _engine(client)

        result = await engine.analyze_slides_with_retry(_SLIDES)

        self.assertEqual(result.screen_text, "kept")

    async def test_a_single_file_keeps_the_models_screen_text(self) -> None:
        client = _FakeClient([self._FULL])
        engine, _ = _engine(client)

        result = await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(result.screen_text, "Headline one")
        self.assertTrue(all(segment.slide is None for segment in result.screen_text_segments))

    def test_the_carousel_instruction_asks_for_every_line_not_the_prominent_ones(self) -> None:
        for phrase in (
            "every legible line on that slide, in reading order",
            "terminal or command-line text",
            "do not pick out only the",
            "Text too small or blurred to read is left\n  out rather than guessed.",
            "exactly\n  one screen_text_segments entry",
        ):
            self.assertIn(phrase, CAROUSEL_SYSTEM_INSTRUCTION)
        # The single-file instruction is unchanged by this.
        self.assertNotIn("every legible line on that slide", SYSTEM_INSTRUCTION)
        self.assertIn("Do not invent text that is not legible.", CAROUSEL_SYSTEM_INSTRUCTION)


class ParallelUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_uploads_overlap_but_never_more_than_four_at_once(self) -> None:
        client = _FakeClient([_RESULT])
        in_flight = 0
        peak = 0
        order: list[str] = []

        async def slow_upload(file):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            order.append(file)
            return SimpleNamespace(name=f"files/{file}", uri=f"https://files.test/files/{file}", mime_type="image/jpeg")

        client.files.upload = slow_upload
        slides = tuple(MediaSlide(path=f"normalized-{n:02d}.jpg", kind=SlideKind.IMAGE) for n in range(1, 10))
        engine, _ = _engine(client)

        await engine.analyze_slides_with_retry(slides)

        self.assertEqual(peak, 4)
        self.assertEqual(sorted(order), [slide.path for slide in slides])
        # Whatever order the uploads finished in, each label sits before its own file.
        (contents,) = client.models.contents_seen
        uploads = [_file_name(part) for part in _media(contents)]
        self.assertEqual(uploads, [f"files/{slide.path}" for slide in slides])
        await engine.drain()
        self.assertEqual(len(client.files.deleted), 9)


class BackgroundCleanupTests(unittest.IsolatedAsyncioTestCase):
    """The answer goes back to the run as soon as Gemini's response is
    parsed; the upload deletes (four at a time) and then the client release
    follow in a background task the engine keeps a reference to."""

    _NINE = tuple(MediaSlide(path=f"normalized-{n:02d}.jpg", kind=SlideKind.IMAGE) for n in range(1, 10))

    def _gated_deletes(self, client: _FakeClient) -> tuple[asyncio.Event, dict]:
        """Every delete waits on the returned event before it is recorded."""
        gate = asyncio.Event()
        stats = {"in_flight": 0, "peak": 0}
        record = client.files.delete

        async def gated_delete(name):
            stats["in_flight"] += 1
            stats["peak"] = max(stats["peak"], stats["in_flight"])
            try:
                await gate.wait()
            finally:
                stats["in_flight"] -= 1
            await record(name)

        client.files.delete = gated_delete
        return gate, stats

    def _spy_release(self, client: _FakeClient) -> list[int]:
        """How many deletes had finished each time the client was released."""
        seen: list[int] = []
        original = GeminiEngine._release

        async def spy(c, api_key):
            seen.append(len(client.files.deleted))
            await original(c, api_key)

        patcher = patch.object(GeminiEngine, "_release", new=staticmethod(spy))
        patcher.start()
        self.addCleanup(patcher.stop)
        return seen

    @staticmethod
    async def _settle() -> None:
        for _ in range(20):
            await asyncio.sleep(0)

    async def test_the_result_returns_before_slow_deletes_finish(self) -> None:
        client = _FakeClient([_RESULT])
        gate, stats = self._gated_deletes(client)
        released = self._spy_release(client)
        engine, _ = _engine(client)

        result = await asyncio.wait_for(engine.analyze_slides_with_retry(self._NINE), timeout=5)

        self.assertIs(result, _RESULT)
        self.assertFalse(gate.is_set())
        self.assertEqual(client.files.deleted, [])
        self.assertEqual(released, [])
        await self._settle()
        self.assertEqual(stats["in_flight"], 4)

        gate.set()
        await engine.drain()

        self.assertEqual(sorted(client.files.deleted), sorted(f"files/{n}" for n in range(1, 10)))
        self.assertEqual(stats["peak"], 4)
        # Released once, and only after every delete had finished.
        self.assertEqual(released, [9])
        self.assertEqual(engine._cleanups, set())

    async def test_a_failed_generate_still_deletes_every_upload_then_releases(self) -> None:
        bad = _api_error(genai_errors.ClientError, 400, "Invalid argument.")
        client = _FakeClient([bad])
        gate, stats = self._gated_deletes(client)
        released = self._spy_release(client)
        engine, _ = _engine(client)

        with self.assertRaises(genai_errors.ClientError):
            await asyncio.wait_for(engine.analyze_slides_with_retry(self._NINE), timeout=5)
        self.assertEqual(client.files.deleted, [])
        self.assertEqual(released, [])
        await self._settle()
        self.assertEqual(stats["in_flight"], 4)

        gate.set()
        await engine.drain()

        self.assertEqual(len(client.files.deleted), 9)
        self.assertEqual(stats["peak"], 4)
        self.assertEqual(released, [9])

    async def test_a_parse_failure_still_deletes_every_upload(self) -> None:
        client = _FakeClient([None])  # parsed None and no text: "empty response"
        released = self._spy_release(client)
        engine, _ = _engine(client)

        with self.assertRaises(RuntimeError):
            await engine.analyze_slides_with_retry(_SLIDES)
        await engine.drain()

        self.assertEqual(sorted(client.files.deleted), ["files/1", "files/2", "files/3"])
        self.assertEqual(released, [3])

    async def test_a_cancelled_run_still_deletes_its_uploads(self) -> None:
        client = _FakeClient([])
        started = asyncio.Event()

        async def hanging_generate(model, contents, config):
            started.set()
            await asyncio.Event().wait()

        client.models.generate_content = hanging_generate
        released = self._spy_release(client)
        engine, _ = _engine(client)

        run = asyncio.create_task(engine.analyze_slides_with_retry(_SLIDES))
        await asyncio.wait_for(started.wait(), timeout=5)
        run.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await run
        await engine.drain()

        self.assertEqual(sorted(client.files.deleted), ["files/1", "files/2", "files/3"])
        self.assertEqual(released, [3])

    async def test_drain_gives_up_after_its_timeout_without_raising(self) -> None:
        client = _FakeClient([_RESULT])
        gate, _ = self._gated_deletes(client)
        engine, _ = _engine(client)
        await engine.analyze_slides_with_retry(_SLIDES)

        loop = asyncio.get_running_loop()
        started = loop.time()
        with self.assertLogs("app.infrastructure.ai.gemini_engine", "INFO") as logs:
            await engine.drain(timeout=0.05)
        self.assertLess(loop.time() - started, 2.0)
        self.assertIn("1 Gemini upload clean-up(s) still running", "\n".join(logs.output))
        # Not cancelled: the clean-up is still there and finishes once it can.
        self.assertEqual(len(engine._cleanups), 1)

        gate.set()
        await engine.drain()
        self.assertEqual(len(client.files.deleted), 3)
        self.assertEqual(engine._cleanups, set())

    async def test_drain_with_nothing_running_returns_at_once(self) -> None:
        engine, _ = _engine(_FakeClient([]))
        await engine.drain(timeout=0)

    async def test_a_failed_delete_neither_fails_the_run_nor_stops_the_others(self) -> None:
        client = _FakeClient([_RESULT])
        record = client.files.delete

        async def flaky_delete(name):
            if name == "files/2":
                raise RuntimeError("delete failed for files/2")
            await record(name)

        client.files.delete = flaky_delete
        engine, _ = _engine(client)

        result = await engine.analyze_slides_with_retry(_SLIDES)
        with self.assertLogs("app.infrastructure.ai.gemini_engine", "INFO") as logs:
            await engine.drain()

        self.assertIs(result, _RESULT)
        self.assertEqual(sorted(client.files.deleted), ["files/1", "files/3"])
        output = "\n".join(logs.output)
        self.assertIn("1 of 3 Gemini uploads could not be deleted (RuntimeError)", output)
        self.assertNotIn("files/2", output)

    async def test_an_own_key_client_is_closed_only_after_its_deletes(self) -> None:
        own = _FakeClient([_RESULT])
        gate, _ = self._gated_deletes(own)
        engine, _ = _engine(_FakeClient([]))

        with patch("app.infrastructure.ai.gemini_engine.genai.Client", return_value=own):
            await engine.analyze_slides_with_retry(_SLIDES, api_key="own-key")
        await self._settle()
        self.assertEqual(own.closed, [])

        gate.set()
        await engine.drain()
        self.assertEqual(len(own.files.deleted), 3)
        self.assertEqual(own.closed, ["async", "sync"])


if __name__ == "__main__":
    unittest.main()
