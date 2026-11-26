"""A multi-slide post in one Gemini request (`analyze_slides_with_retry`),
with the same fake client as test_gemini_engine.py."""

import unittest

from google.genai import errors as genai_errors
from google.genai import types

from app.domain.entities import MediaSlide, ScreenTextSegment, SlideKind, TranscriptSegment, VideoAnalysis
from app.infrastructure.ai.gemini_engine import CAROUSEL_SYSTEM_INSTRUCTION, SYSTEM_INSTRUCTION
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

        self.assertIs(result, _RESULT)
        self.assertEqual(client.files.upload_calls, 3)
        (contents,) = client.models.contents_seen
        labels = [part for part in contents if isinstance(part, str)]
        self.assertEqual(
            labels[:3], ["Slide 1 of 3 (image):", "Slide 2 of 3 (video):", "Slide 3 of 3 (image):"]
        )
        self.assertEqual(labels[3], "Analyze this 3-slide post as instructed.")
        # Each label sits right before its own upload, media before any prompt text.
        self.assertEqual([getattr(part, "name", None) for part in contents[1:6:2]], ["files/1", "files/2", "files/3"])
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
        self.assertEqual(client.files.upload_calls, 6)
        self.assertEqual(len(client.files.deleted), 6)

    async def test_an_upload_that_fails_still_deletes_the_slides_before_it(self) -> None:
        bad = _api_error(genai_errors.ClientError, 400, "Unsupported file.")
        client = _FakeClient([_RESULT], upload_outcomes=[None, bad])
        engine, _ = _engine(client)

        with self.assertRaises(genai_errors.ClientError):
            await engine.analyze_slides_with_retry(_SLIDES)

        self.assertEqual(client.files.deleted, ["files/1"])
        self.assertEqual(client.models.contents_seen, [])


if __name__ == "__main__":
    unittest.main()
