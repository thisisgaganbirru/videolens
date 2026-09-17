"""ProcessRunUseCase's plan-aware behaviour: the cap the run was admitted
under, the resolution long media is read at, and what gets metered."""

import unittest

from app.application.get_run import GetRunUseCase
from app.application.process_run import ProcessRunUseCase
from app.application.record_usage import RecordUsageUseCase
from app.domain.entities import AuthMethod, Principal, RunStatus, TokenUsage, VideoAnalysis
from app.domain.entitlements import MediaResolution, Plan

from .fakes import (
    FakeAccountDirectory,
    FakeAnalysisEngine,
    FakeBillingGateway,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
    FakeUsageMeter,
    make_workspace,
)

ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")


class ProcessRunMeteringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.analysis = FakeAnalysisEngine(result=ANALYSIS)
        self.usage_meter = FakeUsageMeter()
        accounts = FakeAccountDirectory()
        accounts.add_workspace(make_workspace())
        self.use_case = ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            analysis=self.analysis,
            usage=RecordUsageUseCase(usage=self.usage_meter, accounts=accounts, billing=FakeBillingGateway()),
        )

    async def _workspace_run(self, run_id: str = "run-1", max_duration_seconds: int = 1800):
        return await self.runs.create(
            run_id,
            "workspace:ws-pro",
            workspace_id="ws-pro",
            plan=Plan.PRO,
            max_duration_seconds=max_duration_seconds,
        )

    async def test_enforces_the_cap_the_run_was_admitted_under(self) -> None:
        await self._workspace_run(max_duration_seconds=1800)
        await self.runs.create("run-anon", "client:anon")

        await self.use_case.execute("run-1", source_url="https://x.test/v")
        await self.use_case.execute("run-anon", source_url="https://x.test/v")

        self.assertEqual(self.media.enforced_limits, [1800, None])

    async def test_stores_duration_and_token_usage_on_the_run(self) -> None:
        await self._workspace_run()

        await self.use_case.execute("run-1", source_key="runs/run-1/source.mp4")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.duration_seconds, 42.0)
        self.assertEqual(run.usage, TokenUsage(input_tokens=1200, output_tokens=300))
        self.assertEqual(run.status, RunStatus.COMPLETE)

    async def test_long_media_is_analyzed_at_low_resolution(self) -> None:
        await self._workspace_run("short")
        await self._workspace_run("long")
        self.media.duration_seconds = 899.0
        await self.use_case.execute("short", source_url="https://x.test/v")
        self.media.duration_seconds = 901.0
        await self.use_case.execute("long", source_url="https://x.test/v")

        self.assertEqual(self.analysis.resolutions_seen, [MediaResolution.DEFAULT, MediaResolution.LOW])

    async def test_workspace_runs_are_metered_after_the_result_is_stored(self) -> None:
        await self._workspace_run()

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        self.assertEqual(len(self.usage_meter.events), 1)
        event = self.usage_meter.events[0]
        self.assertEqual((event.workspace_id, event.run_id), ("ws-pro", "run-1"))
        self.assertEqual(event.input_tokens, 1200)

    async def test_byok_runs_are_never_metered(self) -> None:
        await self._workspace_run()
        await self.use_case.execute("run-1", source_url="https://x.test/v", gemini_api_key="user-key")
        self.assertEqual(self.usage_meter.events, [])

    async def test_anonymous_runs_are_never_metered(self) -> None:
        await self.runs.create("run-anon", "client:anon")
        await self.use_case.execute("run-anon", source_url="https://x.test/v")
        self.assertEqual(self.usage_meter.events, [])

    async def test_failed_runs_are_not_metered(self) -> None:
        await self._workspace_run()
        self.analysis.error = RuntimeError("boom")

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.FAILED)
        self.assertEqual(self.usage_meter.events, [])

    async def test_a_metering_failure_does_not_fail_the_run(self) -> None:
        class BrokenMeter(FakeUsageMeter):
            async def record(self, event) -> None:
                raise RuntimeError("ledger down")

        accounts = FakeAccountDirectory()
        accounts.add_workspace(make_workspace())
        use_case = ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            analysis=self.analysis,
            usage=RecordUsageUseCase(usage=BrokenMeter(), accounts=accounts, billing=FakeBillingGateway()),
        )
        await self._workspace_run()

        with self.assertLogs("videolens", level="ERROR"):
            await use_case.execute("run-1", source_url="https://x.test/v")

        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)


class WorkspaceOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_workspace_members_share_the_workspace_runs(self) -> None:
        runs = FakeRunRepository()
        await runs.create("run-1", "workspace:ws-pro", workspace_id="ws-pro", plan=Plan.PRO)
        use_case = GetRunUseCase(runs=runs, stale_after_seconds=720)
        member = Principal(
            subject="user:other",
            authenticated=True,
            method=AuthMethod.TOKEN,
            account_id="acct-2",
            workspace_id="ws-pro",
            plan=Plan.PRO,
        )

        run = await use_case.execute("run-1", member)

        self.assertEqual(run.run_id, "run-1")


if __name__ == "__main__":
    unittest.main()
