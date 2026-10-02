"""Plan-aware intake: what changes once a caller belongs to a workspace."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.application.create_run import CreateRunUseCase
from app.domain.entities import AuthMethod, Principal
from app.domain.entitlements import Plan, entitlement_for
from app.domain.errors import PlanLimitError, QuotaExceededError

from .fakes import (
    FakeAccountDirectory,
    FakeJobQueue,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
    FakeSpendCap,
    FakeUploadedFile,
    FakeUsageMeter,
    make_entitlements,
    make_workspace,
)


def _member(workspace_id: str, plan: Plan) -> Principal:
    return Principal(
        subject="user:u1",
        authenticated=True,
        method=AuthMethod.TOKEN,
        account_id="acct-1",
        workspace_id=workspace_id,
        plan=plan,
    )


class PlanAwareCreateRunTests(unittest.IsolatedAsyncioTestCase):
    def _make(self, workspace, *, spend_allowed: bool = True, minutes_used: Decimal | None = None):
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.queue = FakeJobQueue()
        self.spend_cap = FakeSpendCap(allow=spend_allowed)
        self.accounts = FakeAccountDirectory()
        self.usage = FakeUsageMeter()
        if workspace is not None:
            self.accounts.add_workspace(workspace)
            if minutes_used is not None:
                self.usage.preloaded[workspace.workspace_id] = minutes_used
        return CreateRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            queue=self.queue,
            spend_cap=self.spend_cap,
            entitlements=make_entitlements(self.accounts, self.usage, default_max_duration_seconds=180),
            distributed=False,
        )

    async def test_anonymous_runs_keep_the_deployment_limits(self) -> None:
        use_case = self._make(None)
        principal = Principal(subject="client:anon-owner-0001", authenticated=False)
        run = await use_case.execute(
            principal=principal, accept_terms=True, file=FakeUploadedFile(), url=None, gemini_api_key=None
        )
        self.assertEqual(run.owner_id, "client:anon-owner-0001")
        self.assertIsNone(run.workspace_id)
        self.assertEqual(self.media.enforced_limits, [180])
        self.assertEqual(self.spend_cap.consume_calls, 1)

    async def test_paid_workspace_gets_its_plan_cap_and_skips_the_daily_budget(self) -> None:
        workspace = make_workspace(plan=Plan.PRO)
        use_case = self._make(workspace, spend_allowed=False)
        run = await use_case.execute(
            principal=_member(workspace.workspace_id, Plan.PRO),
            accept_terms=True,
            file=FakeUploadedFile(),
            url=None,
            gemini_api_key=None,
        )
        self.assertEqual(run.owner_id, f"workspace:{workspace.workspace_id}")
        self.assertEqual(run.workspace_id, workspace.workspace_id)
        self.assertIs(run.plan, Plan.PRO)
        self.assertEqual(self.media.enforced_limits, [entitlement_for(Plan.PRO).max_duration_seconds])
        self.assertEqual(run.max_duration_seconds, entitlement_for(Plan.PRO).max_duration_seconds)
        self.assertEqual(self.spend_cap.consume_calls, 0)
        self.assertEqual(self.media.upload_limits_mb, [entitlement_for(Plan.PRO).max_file_size_mb])

    async def test_upload_duration_is_stored_on_the_run(self) -> None:
        workspace = make_workspace(plan=Plan.PRO)
        use_case = self._make(workspace)
        self.media.duration_seconds = 91.5
        run = await use_case.execute(
            principal=_member(workspace.workspace_id, Plan.PRO),
            accept_terms=True,
            file=FakeUploadedFile(),
            url=None,
            gemini_api_key=None,
        )
        self.assertEqual(self.runs.runs[run.run_id].duration_seconds, 91.5)

    async def test_workspace_override_beats_the_plan_cap(self) -> None:
        workspace = make_workspace(plan=Plan.PRO, max_duration_seconds=5400)
        use_case = self._make(workspace)
        await use_case.execute(
            principal=_member(workspace.workspace_id, Plan.PRO),
            accept_terms=True,
            file=FakeUploadedFile(),
            url=None,
            gemini_api_key=None,
        )
        self.assertEqual(self.media.enforced_limits, [5400])

    async def test_free_workspace_is_refused_once_its_minutes_are_gone(self) -> None:
        workspace = make_workspace(plan=Plan.FREE)
        use_case = self._make(workspace, minutes_used=Decimal("30"))
        with self.assertRaises(PlanLimitError):
            await use_case.execute(
                principal=_member(workspace.workspace_id, Plan.FREE),
                accept_terms=True,
                file=None,
                url="https://x.test/v.mp4",
                gemini_api_key=None,
            )
        self.assertEqual(self.queue.enqueued, [])
        self.assertEqual(self.spend_cap.consume_calls, 0)

    async def test_free_workspace_still_shares_the_daily_budget(self) -> None:
        workspace = make_workspace(plan=Plan.FREE)
        use_case = self._make(workspace, spend_allowed=False)
        with self.assertRaises(QuotaExceededError):
            await use_case.execute(
                principal=_member(workspace.workspace_id, Plan.FREE),
                accept_terms=True,
                file=None,
                url="https://x.test/v.mp4",
                gemini_api_key=None,
            )

    async def test_paid_plan_with_overage_is_never_refused_for_minutes(self) -> None:
        workspace = make_workspace(plan=Plan.PRO)
        use_case = self._make(workspace, minutes_used=Decimal("100000"))
        run = await use_case.execute(
            principal=_member(workspace.workspace_id, Plan.PRO),
            accept_terms=True,
            file=None,
            url="https://x.test/v.mp4",
            gemini_api_key=None,
        )
        self.assertEqual(run.source_url, "https://x.test/v.mp4")

    async def test_byok_bypasses_the_plan_meter(self) -> None:
        workspace = make_workspace(plan=Plan.FREE)
        use_case = self._make(workspace, minutes_used=Decimal("30"), spend_allowed=False)
        run = await use_case.execute(
            principal=_member(workspace.workspace_id, Plan.FREE),
            accept_terms=True,
            file=None,
            url="https://x.test/v.mp4",
            gemini_api_key="their-key",
        )
        self.assertEqual(self.queue.enqueued[0]["gemini_api_key"], "their-key")
        self.assertIsNotNone(run)

    async def test_signed_in_without_a_directory_behaves_like_before(self) -> None:
        use_case = self._make(None)
        principal = Principal(subject="user:u1", authenticated=True, method=AuthMethod.TOKEN)
        run = await use_case.execute(
            principal=principal, accept_terms=True, file=None, url="https://x.test/v.mp4", gemini_api_key=None
        )
        self.assertEqual(run.owner_id, "user:u1")
        self.assertEqual(self.spend_cap.consume_calls, 1)

    async def test_period_start_bounds_the_meter(self) -> None:
        now = datetime.now(timezone.utc)
        workspace = make_workspace(plan=Plan.FREE, period_start=now - timedelta(days=1))
        use_case = self._make(workspace)
        # An event from before the period must not count.
        from app.domain.entities import UsageEvent

        self.usage.events.append(
            UsageEvent(
                event_id="e0",
                workspace_id=workspace.workspace_id,
                run_id="old",
                minutes_billed=Decimal("30"),
                created_at=now - timedelta(days=2),
            )
        )
        run = await use_case.execute(
            principal=_member(workspace.workspace_id, Plan.FREE),
            accept_terms=True,
            file=None,
            url="https://x.test/v.mp4",
            gemini_api_key=None,
        )
        self.assertIsNotNone(run)


if __name__ == "__main__":
    unittest.main()
