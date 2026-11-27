"""A multi-slide post in one Gemini request (`analyze_slides_with_retry`),
with the same fake client as test_gemini_engine.py."""

import asyncio
import unittest
from types import SimpleNamespace

from google.genai import errors as genai_errors
from google.genai import types

from app.domain.entities import MediaSlide, ScreenTextSegment, SlideKind, TranscriptSegment, VideoAnalysis
from app.infrastructure.ai.gemini_engine import CAROUSEL_SYSTEM_INSTRUCTION, SYSTEM_INSTRUCTION
from app.infrastructure.config import Settings
from tests.infrastructure.ai.test_gemini_engine import _RESULT, _FakeClient, _api_error, _engine

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
        self.assertEqual(len(client.files.deleted), 5)

    async def test_an_upload_that_fails_still_deletes_the_slides_before_it(self) -> None:
        bad = _api_error(genai_errors.ClientError, 400, "Unsupported file.")
        client = _FakeClient([_RESULT], upload_outcomes=[None, bad])
        engine, _ = _engine(client)

        with self.assertRaises(genai_errors.ClientError):
            await engine.analyze_slides_with_retry(_SLIDES)

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
        self.assertEqual(media[0].media_resolution.level, types.PartMediaResolutionLevel.MEDIA_RESOLUTION_ULTRA_HIGH)
        self.assertEqual(media[0].file_data.file_uri, "https://files.test/files/1")
        self.assertEqual(media[0].file_data.mime_type, "application/octet-stream")
        # The video slide is the upload itself, as before.
        self.assertNotIsInstance(media[1], types.Part)
        self.assertEqual(media[1].name, "files/2")
        self.assertIsInstance(media[2], types.Part)

    async def test_the_level_follows_the_setting_and_blank_leaves_it_to_the_model(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, gemini_slide_image_resolution="high")
        await engine.analyze_slides_with_retry(_SLIDES)
        self.assertEqual(
            _media(client.models.contents_seen[0])[0].media_resolution.level,
            types.PartMediaResolutionLevel.MEDIA_RESOLUTION_HIGH,
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
        self.assertEqual(len(client.files.deleted), 9)


if __name__ == "__main__":
    unittest.main()
