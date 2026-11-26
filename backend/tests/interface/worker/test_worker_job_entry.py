"""The arq job function itself (`interface/worker/settings.process_run`)
driven end to end over the real in-process run store, free-run counter and
daily cap: a worker shutdown cancels the job and leaves the run for arq's
retry, a job timeout fails it, and a link that cannot be fetched hands the
free run and the daily-cap unit back. `tests/application/test_shutdown_retry.py`
and `test_daily_cap_refund.py` cover the same rules on the use case with
fakes; here the deadline comes from the job function's own clock."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.application.process_run import ProcessRunUseCase
from app.container import container
from app.domain.entities import MediaVisuals, RunStatus, SavedUpload, VideoAnalysis
from app.domain.errors import RUN_INTERRUPTED_MESSAGE, MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.persistence.run_repository import RunStore
from app.infrastructure.quota.daily_budget import DailyBudget
from app.infrastructure.quota.free_run_allowance import FreeRunAllowanceStore
from app.infrastructure.storage.s3_object_store import S3ObjectStore
from app.interface.worker import settings as worker

SETTINGS = Settings(_env_file=None, gemini_api_key="k", daily_run_cap=5, free_runs_per_device=3)
URL = "https://media.example/v.mp4"
ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")


class _Media:
    """`download_url` either raises `download_error` or waits on `release`
    (a download still in progress when the job is cancelled)."""

    def __init__(self) -> None:
        self.download_error: BaseException | None = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def create_run_dir(self, run_id: str) -> str:
        return os.path.join("runs", run_id)

    def cleanup_run_dir(self, run_id: str) -> None:
        pass

    async def download_url(self, run_id: str, url: str, limits=None) -> SavedUpload:
        self.started.set()
        if self.download_error is not None:
            raise self.download_error
        await self.release.wait()
        return SavedUpload(path=os.path.join("runs", run_id, "download.mp4"), run_dir=os.path.join("runs", run_id))

    async def fetch_captions(self, url: str, limits=None):
        return None

    async def enforce_duration_cap(self, run_id: str, path: str, limits=None) -> float:
        return 12.0

    async def normalize_media(self, src_path: str, run_dir: str) -> str:
        return os.path.join(run_dir, "normalized.mp4")

    async def describe_visuals(self, **kwargs) -> MediaVisuals:
        return MediaVisuals()


class _Analysis:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze_with_retry(self, video_path, on_stage=None, attempts=2, api_key=None, metadata=None):
        self.calls += 1
        return ANALYSIS

    async def analyze_captions(self, captions, api_key=None):
        self.calls += 1
        return ANALYSIS


class WorkerJobEntryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runs = RunStore(SETTINGS)
        self.free_runs = FreeRunAllowanceStore(SETTINGS)
        self.budget = DailyBudget(SETTINGS)
        self.media = _Media()
        self.analysis = _Analysis()
        use_case = ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=S3ObjectStore(SETTINGS),
            analysis=self.analysis,
            free_runs=self.free_runs,
            spend_cap=self.budget,
        )
        for patcher in (
            patch.object(container, "process_run_use_case", use_case),
            patch.object(container.key_vault, "take", AsyncMock(return_value=None)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        # As intake leaves an anonymous free run: one free run and one cap
        # unit, each held for this run.
        await self.runs.create("run-1", "client:owner")
        await self.free_runs.hold("run-1", await self.free_runs.try_consume("device-1", "203.0.113.9"))
        await self.budget.hold("run-1", await self.budget.try_consume())

    async def _used(self) -> tuple[int, int]:
        """(free runs used by the device, cap units used today)."""
        return (await self.free_runs.status("device-1")).used, 5 - await self.budget.remaining()

    async def _start(self) -> asyncio.Task:
        job = asyncio.create_task(worker.process_run({}, "run-1", source_url=URL))
        await asyncio.wait_for(self.media.started.wait(), timeout=5)
        return job

    async def test_a_shutdown_cancellation_leaves_the_run_for_arqs_retry(self) -> None:
        job = await self._start()
        job.cancel()  # what arq does to a running job on SIGTERM
        with self.assertRaises(asyncio.CancelledError):
            await job

        run = await self.runs.get("run-1")
        self.assertEqual(run.status, RunStatus.QUEUED)
        self.assertIsNone(run.error)
        # Both holds are kept for the retry; nothing was handed back yet.
        self.assertEqual(await self._used(), (1, 1))

        # arq runs the job again; this time the download finishes.
        self.media.started.clear()
        self.media.release.set()
        await worker.process_run({}, "run-1", source_url=URL)
        self.assertEqual((await self.runs.get("run-1")).status, RunStatus.COMPLETE)
        self.assertEqual(self.analysis.calls, 1)
        self.assertEqual(await self._used(), (1, 1))
        # Settled: a late release finds no hold.
        self.assertFalse(await self.free_runs.release("run-1", refund=True))
        self.assertFalse(await self.budget.release("run-1", refund=True))

    async def test_a_cancellation_at_the_job_timeout_fails_the_run(self) -> None:
        # A timeout of 0 puts the deadline in the past: this cancellation is
        # arq's job_timeout, which it never retries.
        with patch.object(container.settings, "worker_job_timeout_seconds", 0):
            job = await self._start()
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await job

        run = await self.runs.get("run-1")
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, RUN_INTERRUPTED_MESSAGE)
        # Settled without a refund, as documented for a cancellation
        # (docs/backend/free-runs.md, cost-abuse-protection.md), even though
        # Gemini was never reached; no hold is left for anything to settle.
        self.assertEqual(await self._used(), (1, 1))
        self.assertFalse(await self.free_runs.release("run-1", refund=True))
        self.assertFalse(await self.budget.release("run-1", refund=True))

    async def test_a_link_that_cannot_be_fetched_hands_both_limits_back(self) -> None:
        self.media.download_error = MediaValidationError("Could not fetch that link.")
        await worker.process_run({}, "run-1", source_url=URL)

        run = await self.runs.get("run-1")
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, "Could not fetch that link.")
        self.assertEqual(self.analysis.calls, 0)
        self.assertEqual(await self._used(), (0, 0))


if __name__ == "__main__":
    unittest.main()
