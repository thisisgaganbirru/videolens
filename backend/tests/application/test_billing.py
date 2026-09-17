import unittest
from datetime import datetime, timedelta, timezone

from app.application.billing import (
    ApplyBillingEventUseCase,
    OpenBillingPortalUseCase,
    StartCheckoutUseCase,
)
from app.domain.entities import AuthMethod, BillingEvent, BillingEventKind, Principal
from app.domain.entitlements import Plan, entitlement_for
from app.domain.errors import (
    BillingNotConfiguredError,
    PermissionDeniedError,
    WorkspaceNotFoundError,
)

from .fakes import FakeAccountDirectory, FakeBillingGateway, make_workspace


def _owner(workspace_id: str = "ws-pro", account_id: str = "acct-1", plan: Plan = Plan.PRO) -> Principal:
    return Principal(
        subject="user:owner",
        authenticated=True,
        method=AuthMethod.TOKEN,
        account_id=account_id,
        workspace_id=workspace_id,
        plan=plan,
        email="owner@x.test",
    )


class StartCheckoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.accounts = FakeAccountDirectory()
        self.accounts.add_workspace(make_workspace(plan=Plan.FREE), members={"acct-2": "member"})
        self.billing = FakeBillingGateway()
        self.use_case = StartCheckoutUseCase(accounts=self.accounts, billing=self.billing)

    async def _start(self, principal: Principal, plan: Plan = Plan.PRO) -> str:
        return await self.use_case.execute(
            principal, plan, success_url="https://app/ok", cancel_url="https://app/no"
        )

    async def test_owner_gets_a_checkout_url_for_their_workspace(self) -> None:
        url = await self._start(_owner())

        self.assertEqual(url, "https://checkout.example/ws-pro/pro")
        self.assertEqual(
            self.billing.checkouts, [dict(workspace_id="ws-pro", plan=Plan.PRO, email="owner@x.test")]
        )

    async def test_refuses_when_billing_is_not_configured(self) -> None:
        self.use_case = StartCheckoutUseCase(accounts=self.accounts, billing=FakeBillingGateway(enabled=False))
        with self.assertRaises(BillingNotConfiguredError):
            await self._start(_owner())

    async def test_free_plan_has_nothing_to_check_out(self) -> None:
        with self.assertRaises(PermissionDeniedError):
            await self._start(_owner(), Plan.FREE)

    async def test_anonymous_callers_have_no_workspace(self) -> None:
        with self.assertRaises(WorkspaceNotFoundError):
            await self._start(Principal(subject="client:x", authenticated=False))

    async def test_only_the_owner_can_start_a_subscription(self) -> None:
        with self.assertRaises(PermissionDeniedError):
            await self._start(_owner(account_id="acct-2"))
        self.assertEqual(self.billing.checkouts, [])

    async def test_unknown_workspace_is_not_found(self) -> None:
        with self.assertRaises(WorkspaceNotFoundError):
            await self._start(_owner(workspace_id="ws-missing"))


class OpenBillingPortalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.accounts = FakeAccountDirectory()
        self.billing = FakeBillingGateway()
        self.use_case = OpenBillingPortalUseCase(accounts=self.accounts, billing=self.billing)

    async def test_returns_the_portal_for_the_workspace_customer(self) -> None:
        self.accounts.add_workspace(make_workspace(stripe_customer_id="cus_1"))

        url = await self.use_case.execute(_owner(), return_url="https://app/back")

        self.assertEqual(url, "https://portal.example/cus_1")
        self.assertEqual(self.billing.portals, [dict(customer_id="cus_1", return_url="https://app/back")])

    async def test_refuses_a_workspace_that_never_subscribed(self) -> None:
        self.accounts.add_workspace(make_workspace())
        with self.assertRaises(PermissionDeniedError):
            await self.use_case.execute(_owner(), return_url="https://app/back")

    async def test_refuses_when_billing_is_not_configured(self) -> None:
        self.accounts.add_workspace(make_workspace(stripe_customer_id="cus_1"))
        use_case = OpenBillingPortalUseCase(accounts=self.accounts, billing=FakeBillingGateway(enabled=False))
        with self.assertRaises(BillingNotConfiguredError):
            await use_case.execute(_owner(), return_url="https://app/back")


class ApplyBillingEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.accounts = FakeAccountDirectory()
        self.workspace = make_workspace(plan=Plan.FREE, minutes_included=30)
        self.accounts.add_workspace(self.workspace)
        self.billing = FakeBillingGateway()
        self.use_case = ApplyBillingEventUseCase(accounts=self.accounts, billing=self.billing)
        self.start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=30)

    async def _apply(self, event: BillingEvent):
        self.billing.next_event = event
        return await self.use_case.execute(b"{}", "sig")

    async def test_ignored_events_change_nothing(self) -> None:
        result = await self._apply(BillingEvent(kind=BillingEventKind.IGNORED, event_id="evt-1"))

        self.assertIsNone(result)
        self.assertEqual(self.accounts.subscriptions, [])

    async def test_checkout_completed_upgrades_the_workspace_and_records_the_customer(self) -> None:
        result = await self._apply(
            BillingEvent(
                kind=BillingEventKind.SUBSCRIPTION_STARTED,
                event_id="evt-1",
                customer_id="cus_1",
                subscription_id="sub_1",
                workspace_id="ws-pro",
                plan=Plan.PRO,
                period_start=self.start,
                period_end=self.end,
            )
        )

        self.assertIs(result.plan, Plan.PRO)
        self.assertEqual(result.minutes_included, entitlement_for(Plan.PRO).minutes_included)
        self.assertEqual(result.stripe_customer_id, "cus_1")
        self.assertEqual(result.stripe_subscription_id, "sub_1")
        self.assertEqual((result.period_start, result.period_end), (self.start, self.end))

    async def test_events_without_a_workspace_id_are_matched_by_customer(self) -> None:
        self.workspace.stripe_customer_id = "cus_1"

        result = await self._apply(
            BillingEvent(
                kind=BillingEventKind.SUBSCRIPTION_UPDATED,
                event_id="evt-2",
                customer_id="cus_1",
                subscription_id="sub_1",
                plan=Plan.STUDIO,
            )
        )

        self.assertEqual(result.workspace_id, "ws-pro")
        self.assertIs(result.plan, Plan.STUDIO)
        # No period on the event: the workspace keeps the one it had.
        self.assertEqual(result.period_start, self.workspace.period_start)

    async def test_an_update_without_a_plan_keeps_the_current_one(self) -> None:
        self.workspace.plan = Plan.PRO

        result = await self._apply(
            BillingEvent(
                kind=BillingEventKind.SUBSCRIPTION_UPDATED,
                event_id="evt-3",
                workspace_id="ws-pro",
                subscription_id="sub_1",
            )
        )

        self.assertIs(result.plan, Plan.PRO)

    async def test_subscription_ended_returns_the_workspace_to_free(self) -> None:
        self.workspace.plan = Plan.PRO
        self.workspace.stripe_subscription_id = "sub_1"

        result = await self._apply(
            BillingEvent(
                kind=BillingEventKind.SUBSCRIPTION_ENDED,
                event_id="evt-4",
                workspace_id="ws-pro",
                subscription_id="sub_1",
                plan=Plan.PRO,
            )
        )

        self.assertIs(result.plan, Plan.FREE)
        self.assertEqual(result.minutes_included, entitlement_for(Plan.FREE).minutes_included)
        self.assertIsNone(result.stripe_subscription_id)

    async def test_events_matching_no_workspace_are_dropped(self) -> None:
        result = await self._apply(
            BillingEvent(
                kind=BillingEventKind.SUBSCRIPTION_UPDATED,
                event_id="evt-5",
                customer_id="cus_unknown",
                workspace_id="ws-unknown",
                plan=Plan.PRO,
            )
        )

        self.assertIsNone(result)
        self.assertEqual(self.accounts.subscriptions, [])


if __name__ == "__main__":
    unittest.main()
