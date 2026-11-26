"""A multi-slide post (an Instagram carousel) through `ProcessRunUseCase`:
probed and capped together, normalized slide by slide, analyzed in one
request, and its slide count recorded as a media fact."""

import unittest

from app.application.process_run import ProcessRunUseCase
from app.domain.entities import MediaSlide, RunStatus, SlideKind, SourceMetadata, VideoAnalysis
from app.domain.errors import MediaValidationError

from .fakes import FakeAnalysisEngine, FakeFreeRunAllowance, FakeMediaProcessor, FakeObjectStore, FakeRunRepository

ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="", screen_text="x", markdown="# T")
URL = "https://www.instagram.com/p/POST/"
SLIDES = (
    MediaSlide(path="/tmp/run-1/slide-01.jpg", kind=SlideKind.IMAGE),
    MediaSlide(path="/tmp/run-1/slide-02.mp4", kind=SlideKind.VIDEO),
    MediaSlide(path="/tmp/run-1/slide-03.jpg", kind=SlideKind.IMAGE),
)


class ProcessCarouselTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.media.download_slides = SLIDES
        self.media.slides_duration = 12.0
        self.media.download_metadata = SourceMetadata(platform="Instagram", source_url=URL, title="Post by maker")
        self.analysis = FakeAnalysisEngine(result=ANALYSIS)
        self.free_runs = FakeFreeRunAllowance()
        self.use_case = ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            analysis=self.analysis,
            free_runs=self.free_runs,
        )
        await self.runs.create("run-1", "client:owner")

    async def test_a_carousel_is_analyzed_as_one_post(self) -> None:
        await self.use_case.execute("run-1", source_url=URL)

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual(run.result, ANALYSIS)
        self.assertEqual(run.slide_count, 3)
        self.assertEqual(run.duration_seconds, 12.0)
        # Probed together, never one file at a time.
        self.assertEqual(self.media.enforced_slides, [("run-1", SLIDES)])
        self.assertEqual(self.media.enforced_duration, [])
        # Normalized slide by slide, then analyzed in one request, in order.
        self.assertEqual(self.media.normalize_slides_calls, [(SLIDES, "/tmp/run-1")])
        self.assertEqual(self.media.normalize_calls, [])
        self.assertEqual(self.analysis.calls, [])
        (analyzed, _), = self.analysis.slide_calls
        self.assertEqual([slide.kind for slide in analyzed], [slide.kind for slide in SLIDES])
        self.assertEqual(self.analysis.metadata_seen, [self.media.download_metadata])
        self.assertEqual(self.media.cleaned_up, ["run-1"])

    async def test_the_first_slide_is_the_poster(self) -> None:
        self.media.download_thumbnail_urls = ("https://cdn/cover.jpg",)

        await self.use_case.execute("run-1", source_url=URL)

        (call,) = self.media.visuals_calls
        self.assertEqual(call["media_path"], SLIDES[0].path)
        self.assertEqual(call["thumbnail_urls"], ("https://cdn/cover.jpg",))
        # The post's total says nothing about the first slide's own length.
        self.assertIsNone(call["duration_seconds"])

    async def test_an_all_image_post_records_no_duration(self) -> None:
        self.media.slides_duration = 0.0

        await self.use_case.execute("run-1", source_url=URL)

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertIsNone(run.duration_seconds)
        self.assertEqual(run.slide_count, 3)

    async def test_a_post_over_the_cap_is_rejected_before_gemini(self) -> None:
        self.media.enforce_slides_error = MediaValidationError("The videos in this post are 9:00 long.")

        await self.use_case.execute("run-1", source_url=URL)

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, "The videos in this post are 9:00 long.")
        self.assertEqual(self.analysis.slide_calls, [])
        self.assertIsNone(run.slide_count)

    async def test_a_single_video_link_never_takes_the_slide_path(self) -> None:
        self.media.download_slides = ()

        await self.use_case.execute("run-1", source_url=URL)

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertIsNone(run.slide_count)
        self.assertEqual(self.media.enforced_slides, [])
        self.assertEqual(self.analysis.slide_calls, [])
        self.assertEqual(len(self.analysis.calls), 1)

    async def test_a_failed_slide_count_write_never_fails_the_run(self) -> None:
        async def broken(run_id: str, slide_count: int) -> None:
            raise RuntimeError("store down")

        self.runs.set_slide_count = broken

        await self.use_case.execute("run-1", source_url=URL)

        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)


if __name__ == "__main__":
    unittest.main()
