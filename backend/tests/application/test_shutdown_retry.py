"""A worker shutdown (deploy) cancels a job that arq then runs again; a job
timeout cancels one that arq never retries. The run must survive the first
and fail on the second, with every hold settled exactly once."""

import asyncio
import unittest

from app.application.process_run import ProcessRunUseCase
from app.domain.entities import FreeRunClaim, RunStatus, VideoAnalysis
from app.domain.errors import RUN_INTERRUPTED_MESSAGE, MediaValidationError

from .fakes import (
    FakeAnalysisEngine,
    FakeFreeRunAllowance,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
    FakeSpendCap,
)

ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")
SOURCE_KEY = "runs/run-1/source.mp4"


class RecordingExtraRuns:
    """Stands in for ExtraRunBilling: which runs were billed or voided."""

    def __init__(self) -> None:
        self.completed: list[str] = []
        self.voided: list[str] = []

    async def complete(self, run_id: str) -> None:
        self.completed.append(run_id)

    async def void(self, run_id: str) -> None:
        self.voided.append(run_id)


class ShutdownRetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.storage = FakeObjectStore()
        self.analysis = FakeAnalysisEngine(result=ANALYSIS)
        self.free_runs = FakeFreeRunAllowance()
        self.spend_cap = FakeSpendCap()
        self.extra_runs = RecordingExtraRuns()
        self.use_case = ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=self.storage,
            analysis=self.analysis,
            free_runs=self.free_runs,
            extra_runs=self.extra_runs,
            spend_cap=self.spend_cap,
        )
        await self.runs.create("run-1", "client:owner")
        # As intake leaves a free anonymous run: a free run and a daily cap
        # unit, each held for this run.
        claim = await self.free_runs.try_consume("device-1", "203.0.113.9")
        await self.free_runs.hold("run-1", claim)
        await self.spend_cap.hold("run-1", await self.spend_cap.try_consume())

    @staticmethod
    def _future() -> float:
        return asyncio.get_running_loop().time() + 600

    async def _cancelled(self, **kwargs) -> None:
        with self.assertRaises(asyncio.CancelledError):
            await self.use_case.execute("run-1", **kwargs)

    async def test_shutdown_in_gemini_leaves_the_run_for_the_retry(self) -> None:
        self.analysis.error = asyncio.CancelledError()
        await self._cancelled(source_key=SOURCE_KEY, deadline=self._future())

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.QUEUED)
        self.assertIsNone(run.error)
        self.assertEqual(self.storage.deleted, [])  # the retry downloads it again
        self.assertIn("run-1", self.free_runs.held)
        self.assertEqual(self.extra_runs.voided, [])
        # Gemini was reached: the unit is kept for good, so no hold is left
        # for the retry to refund.
        self.assertEqual(self.spend_cap.held, {})
        self.assertEqual(self.spend_cap.used, 1)

        # arq's retry, on the next worker.
        self.analysis.error = None
        await self.use_case.execute("run-1", source_key=SOURCE_KEY, deadline=self._future())

        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)
        self.assertEqual(self.extra_runs.completed, ["run-1"])
        self.assertEqual(self.storage.deleted, [SOURCE_KEY])
        self.assertEqual(self.free_runs.held, {})
        self.assertEqual(self.free_runs.refunds, [])
        self.assertEqual(self.spend_cap.refunds, [])
        self.assertEqual(self.spend_cap.used, 1)

    async def test_shutdown_before_gemini_keeps_both_holds_and_refunds_once(self) -> None:
        self.media.download_error = asyncio.CancelledError()
        await self._cancelled(source_url="https://x.test/v.mp4", deadline=self._future())

        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.QUEUED)
        self.assertIn("run-1", self.free_runs.held)
        self.assertIn("run-1", self.spend_cap.held)

        # The retry finds the link gone: rejected before analysis, so the
        # free run and the unit go back, once each.
        self.media.download_error = MediaValidationError("Could not fetch that link.")
        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4", deadline=self._future())

        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.FAILED)
        self.assertEqual(len(self.free_runs.refunds), 1)
        self.assertEqual(len(self.spend_cap.refunds), 1)
        self.assertEqual(self.spend_cap.used, 0)
        self.assertEqual(self.extra_runs.voided, ["run-1"])

    async def test_timeout_still_fails_the_run(self) -> None:
        self.analysis.error = asyncio.CancelledError()
        # The deadline has passed: arq's job_timeout cancelled it.
        deadline = asyncio.get_running_loop().time()
        await self._cancelled(source_key=SOURCE_KEY, deadline=deadline)

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, RUN_INTERRUPTED_MESSAGE)
        self.assertEqual(self.storage.deleted, [SOURCE_KEY])
        self.assertEqual(self.extra_runs.voided, ["run-1"])
        self.assertEqual(self.free_runs.held, {})
        # Reached Gemini: kept, not refunded.
        self.assertEqual(self.spend_cap.refunds, [])

    async def test_no_deadline_treats_every_cancellation_as_final(self) -> None:
        # The in-process runner: nothing would retry the run.
        self.analysis.error = asyncio.CancelledError()
        await self._cancelled(source_key=SOURCE_KEY)
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.FAILED)

    async def test_own_key_run_fails_on_shutdown_and_never_uses_the_shared_key(self) -> None:
        # An own-key run holds no free run and no unit.
        self.free_runs.held.clear()
        self.spend_cap.held.clear()
        self.runs.runs["run-1"].admitted_byok = True
        self.analysis.error = asyncio.CancelledError()
        await self._cancelled(source_key=SOURCE_KEY, gemini_api_key="own-key", deadline=self._future())

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, RUN_INTERRUPTED_MESSAGE)
        self.assertEqual(self.storage.deleted, [SOURCE_KEY])

        # arq's retry: the single-use vault is empty now.
        self.analysis.error = None
        await self.use_case.execute("run-1", source_key=SOURCE_KEY, gemini_api_key=None, deadline=self._future())

        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.FAILED)
        self.assertEqual([key for _, key in self.analysis.calls], ["own-key"])
        self.assertEqual(self.free_runs.refunds, [])
        self.assertEqual(self.spend_cap.refunds, [])

    async def test_a_stale_sweep_between_attempts_refunds_once(self) -> None:
        # Shutdown, then no worker for longer than the stale threshold: the
        # sweep fails the run and hands the free run back; the late retry is
        # dropped and must not hand it back again.
        self.media.download_error = asyncio.CancelledError()
        await self._cancelled(source_url="https://x.test/v.mp4", deadline=self._future())
        await self.runs.set_error("run-1", "The analysis didn't finish. Please try again.")
        await self.free_runs.release("run-1", refund=True)

        self.media.download_error = None
        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4", deadline=self._future())

        self.assertEqual(self.analysis.calls, [])
        self.assertEqual(len(self.free_runs.refunds), 1)
        self.assertIsInstance(self.free_runs.refunds[0], FreeRunClaim)


if __name__ == "__main__":
    unittest.main()
