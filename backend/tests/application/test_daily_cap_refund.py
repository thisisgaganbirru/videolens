"""The shared daily cap (`DAILY_RUN_CAP`) keeps a unit only for runs that
reach Gemini: every intake rejection and every worker failure before
analysis hands it back (mem/20261120-fix-shared-limit-abuse.md)."""

import asyncio
import unittest

from app.application.create_run import CreateRunUseCase
from app.application.process_run import ProcessRunUseCase
from app.domain.entities import CaptionTrack, Principal, RunStatus, VideoAnalysis
from app.domain.errors import InvalidSourceError, MediaValidationError, RunSchedulingError
from app.domain.policies import is_well_formed_source_url

from .fakes import (
    FakeAnalysisEngine,
    FakeDeviceTokens,
    FakeFreeRunAllowance,
    FakeJobQueue,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
    FakeSpendCap,
    FakeUploadedFile,
)

PRINCIPAL = Principal(subject="client:test-owner", authenticated=False)
ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")


class IntakeCapRefundTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.queue = FakeJobQueue()
        self.spend_cap = FakeSpendCap()
        self.use_case = CreateRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            queue=self.queue,
            spend_cap=self.spend_cap,
            free_runs=FakeFreeRunAllowance(enabled=False),
            device_tokens=FakeDeviceTokens(),
            distributed=False,
        )

    async def _upload(self, **kwargs):
        return await self.use_case.execute(
            principal=PRINCIPAL, accept_terms=True, file=FakeUploadedFile(), url=None, **kwargs
        )

    async def test_bad_media_hands_the_unit_back(self) -> None:
        self.media.save_upload_error = MediaValidationError("Not a video.")
        with self.assertRaises(MediaValidationError):
            await self._upload(gemini_api_key=None)
        self.assertEqual(self.spend_cap.consume_calls, 1)
        self.assertEqual(self.spend_cap.used, 0)
        self.assertEqual(self.spend_cap.held, {})

    async def test_over_long_upload_hands_the_unit_back(self) -> None:
        self.media.enforce_duration_error = MediaValidationError("Too long.")
        with self.assertRaises(MediaValidationError):
            await self._upload(gemini_api_key=None)
        self.assertEqual(self.spend_cap.used, 0)

    async def test_unschedulable_run_hands_the_unit_back(self) -> None:
        self.queue.enqueue_error = RuntimeError("redis down")
        with self.assertRaises(RunSchedulingError):
            await self._upload(gemini_api_key=None)
        self.assertEqual(self.spend_cap.used, 0)

    async def test_accepted_run_keeps_and_holds_its_unit(self) -> None:
        run = await self._upload(gemini_api_key=None)
        self.assertEqual(self.spend_cap.used, 1)
        self.assertIn(run.run_id, self.spend_cap.held)

    async def test_byok_never_touches_the_cap(self) -> None:
        self.media.save_upload_error = MediaValidationError("Not a video.")
        with self.assertRaises(MediaValidationError):
            await self._upload(gemini_api_key="user-key")
        self.assertEqual(self.spend_cap.consume_calls, 0)
        self.assertEqual(self.spend_cap.refunds, [])

    async def test_malformed_url_is_refused_before_the_cap(self) -> None:
        for url in ("not a url", "ftp://x.test/v", "https://", "javascript:alert(1)", "https://x.test:99999/v"):
            with self.assertRaises(InvalidSourceError):
                await self.use_case.execute(
                    principal=PRINCIPAL, accept_terms=True, file=None, url=url, gemini_api_key=None
                )
        self.assertEqual(self.spend_cap.consume_calls, 0)
        self.assertEqual(self.queue.enqueued, [])


class UrlSyntaxTests(unittest.TestCase):
    def test_accepts_ordinary_links(self) -> None:
        self.assertTrue(is_well_formed_source_url("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(is_well_formed_source_url("http://x.test:8080/v.mp4"))

    def test_rejects_junk(self) -> None:
        for url in ("", "x.test/v", "https://x .test/v", "https://x.test/\nv", "file:///etc/passwd", "https://" + "a" * 3000):
            self.assertFalse(is_well_formed_source_url(url), url)


class WorkerCapRefundTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.analysis = FakeAnalysisEngine(result=ANALYSIS)
        self.spend_cap = FakeSpendCap()
        self.use_case = ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            analysis=self.analysis,
            free_runs=FakeFreeRunAllowance(),
            spend_cap=self.spend_cap,
        )
        await self.runs.create("run-1", "client:owner")
        # As intake leaves it: one unit taken and held for this run.
        claim = await self.spend_cap.try_consume()
        await self.spend_cap.hold("run-1", claim)

    async def test_unreachable_link_hands_the_unit_back(self) -> None:
        self.media.download_error = MediaValidationError("Could not fetch that link.")
        await self.use_case.execute("run-1", source_url="https://nonexistent.invalid/x")
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.FAILED)
        self.assertEqual(self.spend_cap.used, 0)

    async def test_over_long_link_hands_the_unit_back(self) -> None:
        self.media.enforce_duration_error = MediaValidationError("Too long.")
        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")
        self.assertEqual(self.spend_cap.used, 0)

    async def test_normalize_failure_hands_the_unit_back(self) -> None:
        self.media.normalize_error = MediaValidationError("Could not read it.")
        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")
        self.assertEqual(self.analysis.calls, [])
        self.assertEqual(self.spend_cap.used, 0)

    async def test_a_run_that_reaches_gemini_keeps_its_unit(self) -> None:
        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)
        self.assertEqual(self.spend_cap.used, 1)
        self.assertEqual(self.spend_cap.held, {})

    async def test_a_gemini_failure_keeps_its_unit(self) -> None:
        self.analysis.error = RuntimeError("gemini exploded")
        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.FAILED)
        self.assertEqual(self.spend_cap.used, 1)

    async def test_caption_fallback_that_reaches_gemini_keeps_its_unit(self) -> None:
        self.media.download_error = MediaValidationError("Could not fetch that link.")
        self.media.captions = CaptionTrack(text="hi", language="en", automatic=True)
        await self.use_case.execute("run-1", source_url="https://x.test/v")
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)
        self.assertEqual(self.spend_cap.used, 1)

    async def test_cancellation_keeps_its_unit(self) -> None:
        # arq may run a cancelled job again, so its unit is not handed back.
        self.media.download_error = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")
        self.assertEqual(self.spend_cap.used, 1)

    async def test_release_happens_once(self) -> None:
        self.media.download_error = MediaValidationError("Could not fetch that link.")
        await self.use_case.execute("run-1", source_url="https://nonexistent.invalid/x")
        self.assertEqual(await self.spend_cap.release("run-1", refund=True), False)
        self.assertEqual(len(self.spend_cap.refunds), 1)


if __name__ == "__main__":
    unittest.main()
