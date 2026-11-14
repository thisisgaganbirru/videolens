"""A run the stale-run check already failed does no work in the worker.

`GetRunUseCase` fails a queued/processing run that has not been written for
longer than its job could take (timeout + 120 s). The arq job can still be
picked up afterwards, or still be running: the worker now re-reads the run at
the start and before FFmpeg and Gemini, and stops when it has ended or its
record is gone. The store never writes to an ended run again, so whichever of
the result and the sweep's failure lands first is the one outcome the client
sees. A free run the sweep-failed run held goes back exactly once.
"""

import unittest
from datetime import datetime, timedelta, timezone

from app.application.get_run import RUN_ABANDONED_MESSAGE, GetRunUseCase
from app.application.process_run import BYOK_KEY_EXPIRED_MESSAGE, ProcessRunUseCase
from app.domain.entities import CaptionTrack, Principal, RunStatus, VideoAnalysis
from app.domain.entitlements import MediaLimits, MediaTier
from app.domain.errors import MediaValidationError

from .fakes import (
    FakeAccountFreeRunAllowance,
    FakeAnalysisEngine,
    FakeFreeRunAllowance,
    FakeLongRunGuard,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
)

OWNER = Principal(subject="client:owner-0123456789", authenticated=False)
ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")
LONG = MediaLimits(
    tier=MediaTier.SIGNED_IN_BYOK, max_duration_seconds=600, max_file_size_mb=500, long_run_key="acct-1"
)


class StaleRunSkipTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.storage = FakeObjectStore()
        self.analysis = FakeAnalysisEngine(result=ANALYSIS)
        self.free_runs = FakeFreeRunAllowance()
        self.accounts = FakeAccountFreeRunAllowance()
        self.guard = FakeLongRunGuard()
        self.sweep = GetRunUseCase(
            runs=self.runs,
            stale_after_seconds=720,
            free_runs=self.free_runs,
            account_free_runs=self.accounts,
        )

    def _worker(self) -> ProcessRunUseCase:
        return ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=self.storage,
            analysis=self.analysis,
            free_runs=self.free_runs,
            account_free_runs=self.accounts,
            long_runs=self.guard,
        )

    async def _admit(self, run_id: str = "run-1", *, device_free_run: bool = True, account_free_run: bool = False):
        await self.runs.create(run_id, OWNER.subject)
        if device_free_run:
            claim = await self.free_runs.try_consume("device-1", "203.0.113.9")
            await self.free_runs.hold(run_id, claim)
        if account_free_run:
            claim = await self.accounts.try_consume("acct-1")
            await self.accounts.hold(run_id, claim)

    async def _sweep(self, run_id: str = "run-1"):
        """What a poll does once the run has gone quiet for too long."""
        self.runs.runs[run_id].updated_at = datetime.now(timezone.utc) - timedelta(seconds=900)
        return await self.sweep.execute(run_id, OWNER)

    def _assert_no_work(self) -> None:
        self.assertEqual(self.media.download_calls, [])
        self.assertEqual(self.media.caption_calls, [])
        self.assertEqual(self.media.normalize_calls, [])
        self.assertEqual(self.media.enforced_duration, [])
        self.assertEqual(self.storage.downloaded, [])
        self.assertEqual(self.analysis.calls, [])
        self.assertEqual(self.analysis.caption_calls, [])

    # --- the job is picked up after the sweep failed the run --------------

    async def test_a_link_job_for_a_swept_run_does_no_work_and_cleans_up(self) -> None:
        await self._admit()
        reported = await self._sweep()
        self.assertEqual(reported.status, RunStatus.FAILED)

        await self._worker().execute("run-1", source_url="https://example.com/v", gemini_api_key=None)

        self._assert_no_work()
        self.assertEqual(self.media.cleaned_up, ["run-1"])
        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, RUN_ABANDONED_MESSAGE)
        self.assertIsNone(run.stage)

    async def test_an_upload_job_for_a_swept_run_deletes_its_s3_source_without_downloading(self) -> None:
        await self._admit()
        await self._sweep()

        await self._worker().execute("run-1", source_key="uploads/run-1/source.mp4")

        self._assert_no_work()
        self.assertEqual(self.storage.deleted, ["uploads/run-1/source.mp4"])
        self.assertEqual(self.media.cleaned_up, ["run-1"])

    async def test_a_swept_long_upload_releases_the_slot_intake_took(self) -> None:
        await self._admit(device_free_run=False)
        self.guard.holders["acct-1"] = "run-1"  # intake claimed it for the long upload
        await self._sweep()

        await self._worker().execute("run-1", source_key="uploads/run-1/source.mp4", gemini_api_key="k", limits=LONG)

        self._assert_no_work()
        self.assertEqual(self.guard.release_calls, [("acct-1", "run-1")])
        self.assertNotIn("acct-1", self.guard.holders)

    # --- the free run goes back exactly once -------------------------------

    async def test_the_sweep_refunds_the_free_run_and_the_worker_does_not_refund_again(self) -> None:
        await self._admit()
        await self._sweep()
        self.assertEqual(len(self.free_runs.refunds), 1)
        self.assertEqual(self.free_runs.device_counts["device-1"], 0)

        await self._worker().execute("run-1", source_url="https://example.com/v")
        # An arq retry of the same job: still nothing more.
        await self._worker().execute("run-1", source_url="https://example.com/v")

        self.assertEqual(len(self.free_runs.refunds), 1)
        self.assertEqual(self.free_runs.device_counts["device-1"], 0)

    async def test_repeated_polls_of_a_swept_run_refund_once(self) -> None:
        await self._admit()
        await self._sweep()
        await self.sweep.execute("run-1", OWNER)
        await self._sweep()

        self.assertEqual(len(self.free_runs.refunds), 1)

    async def test_the_worker_refunds_a_swept_run_the_sweep_could_not_refund(self) -> None:
        # The sweep's release failed (or it was not wired): the hold is
        # still there when the job is picked up, and the worker hands it back.
        self.sweep = GetRunUseCase(runs=self.runs, stale_after_seconds=720)
        await self._admit()
        await self._sweep()
        self.assertEqual(self.free_runs.refunds, [])

        await self._worker().execute("run-1", source_url="https://example.com/v")
        await self._worker().execute("run-1", source_url="https://example.com/v")

        self.assertEqual(len(self.free_runs.refunds), 1)

    async def test_an_account_free_run_goes_back_once_too(self) -> None:
        await self._admit(device_free_run=False, account_free_run=True)
        await self._sweep()
        await self._worker().execute("run-1", source_url="https://example.com/v")

        self.assertEqual(len(self.accounts.refunds), 1)
        self.assertEqual(self.accounts.used("acct-1"), 0)

    async def test_a_completed_run_reaching_the_worker_again_is_not_refunded(self) -> None:
        await self._admit()
        await self._worker().execute("run-1", source_url="https://example.com/v")
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)
        calls = len(self.analysis.calls)

        await self._worker().execute("run-1", source_url="https://example.com/v")

        self.assertEqual(len(self.analysis.calls), calls)
        self.assertEqual(self.free_runs.refunds, [])
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)

    async def test_a_job_whose_record_is_gone_does_no_work_and_is_not_refunded(self) -> None:
        claim = await self.free_runs.try_consume("device-1", "203.0.113.9")
        await self.free_runs.hold("gone", claim)

        await self._worker().execute("gone", source_url="https://example.com/v", gemini_api_key="k")

        self._assert_no_work()
        self.assertEqual(self.free_runs.release_calls, [("gone", False)])
        self.assertEqual(self.free_runs.refunds, [])
        self.assertEqual(self.media.cleaned_up, ["gone"])

    # --- the sweep fails the run while the worker is busy with it ----------

    async def test_swept_during_normalize_stops_before_gemini(self) -> None:
        await self._admit()
        test = self
        original = self.media.normalize_media

        async def slow_normalize(src_path, run_dir):
            path = await original(src_path, run_dir)
            await test._sweep()
            return path

        self.media.normalize_media = slow_normalize  # type: ignore[method-assign]

        await self._worker().execute("run-1", source_url="https://example.com/v")

        self.assertEqual(self.analysis.calls, [])
        run = self.runs.runs["run-1"]
        self.assertEqual((run.status, run.error), (RunStatus.FAILED, RUN_ABANDONED_MESSAGE))
        self.assertIsNone(run.result)
        self.assertEqual(len(self.free_runs.refunds), 1)
        self.assertEqual(self.media.cleaned_up, ["run-1"])

    async def test_swept_during_a_long_download_stops_before_normalize(self) -> None:
        await self._admit()
        test = self
        original = self.media.download_url

        async def slow_download(run_id, url, limits=None):
            saved = await original(run_id, url, limits)
            await test._sweep()
            return saved

        self.media.download_url = slow_download  # type: ignore[method-assign]

        await self._worker().execute("run-1", source_url="https://example.com/v")

        self.assertEqual(self.media.normalize_calls, [])
        self.assertEqual(self.analysis.calls, [])
        self.assertEqual(self.runs.runs["run-1"].error, RUN_ABANDONED_MESSAGE)

    async def test_swept_while_gemini_ran_the_failure_stands_and_the_result_is_dropped(self) -> None:
        await self._admit()

        async def sweep_first():
            await self._sweep()

        self.runs.before_result = sweep_first

        await self._worker().execute("run-1", source_url="https://example.com/v")

        self.assertEqual(len(self.analysis.calls), 1)
        run = self.runs.runs["run-1"]
        self.assertEqual((run.status, run.error), (RunStatus.FAILED, RUN_ABANDONED_MESSAGE))
        self.assertIsNone(run.result)
        # The client reads the same failure it was already shown.
        polled = await self.sweep.execute("run-1", OWNER)
        self.assertEqual((polled.status, polled.error), (RunStatus.FAILED, RUN_ABANDONED_MESSAGE))
        self.assertEqual(len(self.free_runs.refunds), 1)
        self.assertEqual(self.media.cleaned_up, ["run-1"])

    async def test_swept_during_caption_fetch_stops_before_the_caption_gemini_call(self) -> None:
        await self._admit()
        self.media.download_error = MediaValidationError("HTTP Error 403: Forbidden")
        self.media.captions = CaptionTrack(text="hello", language="en", automatic=False)
        self.analysis.caption_result = ANALYSIS
        test = self
        original = self.media.fetch_captions

        async def slow_captions(url, limits=None):
            track = await original(url, limits)
            await test._sweep()
            return track

        self.media.fetch_captions = slow_captions  # type: ignore[method-assign]

        await self._worker().execute("run-1", source_url="https://example.com/v")

        self.assertEqual(self.analysis.caption_calls, [])
        run = self.runs.runs["run-1"]
        # Not the download error: the run's outcome is the sweep's failure.
        self.assertEqual((run.status, run.error), (RunStatus.FAILED, RUN_ABANDONED_MESSAGE))
        self.assertEqual(len(self.free_runs.refunds), 1)

    async def test_a_sweep_that_loses_the_race_reports_the_completed_run(self) -> None:
        # The sweep read `processing` (stale), then the worker completed the
        # run before the sweep's write: the store refuses the failure and the
        # poll returns the result, so the client never sees a phantom failure.
        await self._admit()
        await self.runs.set_status("run-1", RunStatus.PROCESSING)
        stale = self.runs.runs["run-1"].model_copy(deep=True)
        stale.updated_at = datetime.now(timezone.utc) - timedelta(seconds=900)
        await self.runs.set_result("run-1", ANALYSIS)
        real_get = self.runs.get
        reads = []

        async def stale_first_read(run_id):
            reads.append(run_id)
            return stale if len(reads) == 1 else await real_get(run_id)

        self.runs.get = stale_first_read  # type: ignore[method-assign]

        polled = await self.sweep.execute("run-1", OWNER)

        self.assertEqual(polled.status, RunStatus.COMPLETE)
        self.assertEqual(polled.result, ANALYSIS)
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)
        self.assertEqual(self.free_runs.refunds, [])

    # --- unchanged paths ---------------------------------------------------

    async def test_a_normal_run_is_unchanged(self) -> None:
        await self._admit()

        await self._worker().execute("run-1", source_url="https://example.com/v", gemini_api_key=None)

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual(len(self.analysis.calls), 1)
        self.assertEqual(self.free_runs.release_calls, [("run-1", False)])
        self.assertEqual(self.free_runs.refunds, [])
        self.assertEqual(self.runs.skipped_writes, [])

    async def test_the_byok_expired_key_refusal_still_applies_to_a_live_run(self) -> None:
        await self.runs.create("run-1", OWNER.subject, admitted_byok=True)

        await self._worker().execute("run-1", source_url="https://example.com/v", gemini_api_key=None)

        self._assert_no_work()
        run = self.runs.runs["run-1"]
        self.assertEqual((run.status, run.error), (RunStatus.FAILED, BYOK_KEY_EXPIRED_MESSAGE))
        self.assertEqual(self.media.cleaned_up, ["run-1"])

    async def test_a_swept_byok_run_keeps_the_sweep_failure_not_the_key_message(self) -> None:
        await self.runs.create("run-1", OWNER.subject, admitted_byok=True)
        await self._sweep()

        await self._worker().execute("run-1", source_url="https://example.com/v", gemini_api_key=None)

        self._assert_no_work()
        self.assertEqual(self.runs.runs["run-1"].error, RUN_ABANDONED_MESSAGE)


if __name__ == "__main__":
    unittest.main()
