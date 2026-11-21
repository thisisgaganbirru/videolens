import unittest
from datetime import datetime, timedelta, timezone

from app.application.get_run import GetRunUseCase
from app.domain.entities import Principal, RunStatus, VideoAnalysis
from app.domain.errors import RunNotFoundError

from app.domain.entities import SpendClaim

from .fakes import FakeRunRepository, FakeSpendCap

ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")


class GetRunUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.use_case = GetRunUseCase(runs=self.runs, stale_after_seconds=720)

    async def test_returns_the_run_when_the_owner_matches(self) -> None:
        created = await self.runs.create("run-1", "client:owner-1")
        principal = Principal(subject="client:owner-1", authenticated=False)

        run = await self.use_case.execute("run-1", principal)

        self.assertEqual(run.run_id, created.run_id)

    async def test_raises_not_found_when_the_run_does_not_exist(self) -> None:
        principal = Principal(subject="client:owner-1", authenticated=False)
        with self.assertRaises(RunNotFoundError):
            await self.use_case.execute("does-not-exist", principal)

    async def test_raises_not_found_rather_than_leaking_another_owners_run(self) -> None:
        await self.runs.create("run-1", "client:owner-1")
        other_principal = Principal(subject="client:owner-2", authenticated=False)

        with self.assertRaises(RunNotFoundError):
            await self.use_case.execute("run-1", other_principal)


if __name__ == "__main__":
    unittest.main()


class StaleRunTests(unittest.IsolatedAsyncioTestCase):
    """A run whose owning process died has nothing left to fail it."""

    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.use_case = GetRunUseCase(runs=self.runs, stale_after_seconds=720)
        self.principal = Principal(subject="client:owner", authenticated=False)
        await self.runs.create("run-1", "client:owner")

    def _age(self, run_id: str, seconds: int) -> None:
        run = self.runs.runs[run_id]
        run.updated_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)

    async def test_a_processing_run_with_no_recent_update_is_reported_failed(self) -> None:
        await self.runs.set_status("run-1", RunStatus.PROCESSING)
        self._age("run-1", 900)

        run = await self.use_case.execute("run-1", self.principal)

        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertIn("stopped responding", run.error)

    async def test_the_failure_is_persisted_so_history_agrees(self) -> None:
        await self.runs.set_status("run-1", RunStatus.PROCESSING)
        self._age("run-1", 900)

        await self.use_case.execute("run-1", self.principal)

        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.FAILED)

    async def test_a_recently_updated_processing_run_is_left_alone(self) -> None:
        await self.runs.set_status("run-1", RunStatus.PROCESSING)
        self._age("run-1", 60)

        run = await self.use_case.execute("run-1", self.principal)

        self.assertEqual(run.status, RunStatus.PROCESSING)

    async def test_a_queued_run_can_also_go_stale(self) -> None:
        # Enqueued but never picked up - the worker died before starting it.
        self._age("run-1", 900)

        run = await self.use_case.execute("run-1", self.principal)

        self.assertEqual(run.status, RunStatus.FAILED)

    async def test_a_completed_run_is_never_reinterpreted_by_age(self) -> None:
        await self.runs.set_result("run-1", ANALYSIS)
        self._age("run-1", 999999)

        run = await self.use_case.execute("run-1", self.principal)

        self.assertEqual(run.status, RunStatus.COMPLETE)


class StaleRunDailyCapTests(unittest.IsolatedAsyncioTestCase):
    """A run the sweep fails hands its daily cap unit back only when it
    stopped before reaching Gemini; once, whoever settles it later."""

    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.cap = FakeSpendCap()
        self.use_case = GetRunUseCase(runs=self.runs, stale_after_seconds=720, spend_cap=self.cap)
        self.principal = Principal(subject="client:owner", authenticated=False)

    async def _stale(self, run_id: str, stage: str | None) -> None:
        await self.runs.create(run_id, "client:owner")
        await self.runs.set_status(run_id, RunStatus.PROCESSING)
        await self.cap.hold(run_id, SpendClaim(day="2026-01-01"))
        run = self.runs.runs[run_id]
        run.stage = stage
        run.updated_at = datetime.now(timezone.utc) - timedelta(seconds=900)

    async def test_a_run_that_never_reached_gemini_gets_its_unit_back_once(self) -> None:
        for stage in (None, "downloading", "normalizing"):
            with self.subTest(stage=stage):
                run_id = f"run-{stage}"
                await self._stale(run_id, stage)
                self.assertEqual((await self.use_case.execute(run_id, self.principal)).status, RunStatus.FAILED)
                await self.use_case.execute(run_id, self.principal)
                # The worker dropping the job later releases again: a no-op.
                self.assertFalse(await self.cap.release(run_id, refund=False))
        self.assertEqual(len(self.cap.refunds), 3)

    async def test_a_run_that_reached_gemini_keeps_its_unit_spent(self) -> None:
        for stage in ("analyzing_captions", "uploading_to_gemini", "analyzing"):
            with self.subTest(stage=stage):
                await self._stale(f"run-{stage}", stage)
                await self.use_case.execute(f"run-{stage}", self.principal)
        self.assertEqual(self.cap.refunds, [])
        self.assertEqual(len(self.cap.held), 3)  # left for the worker, which keeps them spent
