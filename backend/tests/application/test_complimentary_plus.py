"""Complimentary Plus (docs/backend/billing.md): `accounts.complimentary_plus`
puts an account on the paid plan with or without Stripe and never bills it.
Paid media limits and included runs, then a 402 like a free account out of
runs (never an extra run, a ledger row or a meter event); saved history on,
with no post-cancel window; a real subscription on the same account wins;
everyone else is unchanged.

Billing is the real `BillingPlans` over the in-memory stores and the fake
Stripe gateway, as in test_billing; the flag comes from a directory double
standing in for the owner's hand-written SQL."""

import unittest
from datetime import datetime, timedelta, timezone

from app.application.get_account import GetAccountUseCase
from app.application.get_billing import GetBillingUseCase
from app.application.get_free_runs import GetFreeRunsUseCase
from app.application.open_billing_portal import OpenBillingPortalUseCase
from app.application.process_run import ProcessRunUseCase
from app.application.restore_account import RestoreAccountUseCase
from app.application.saved_history import SavedHistory, SavedHistoryQueries
from app.application.start_checkout import StartCheckoutUseCase
from app.domain.entities import Account, AuthMethod, FreeRunPeriod, Principal, RunStatus
from app.domain.entitlements import MediaTier, Plan
from app.domain.errors import BillingNotConfiguredError, ComplimentaryPlanError, FreeRunsExhaustedError
from app.infrastructure.persistence.account_deleter import InMemoryAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
from app.infrastructure.persistence.saved_run_repository import InMemorySavedRuns

from .fakes import FakeDeviceTokens, FakeFreeRunAllowance, FakeRunRepository
from .test_billing import ACCOUNT, HELD, SETTINGS, URL, _Billing, _person, _Pipeline

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


class _Flags:
    """AccountDirectory double: only `get_account`, which is all BillingPlans
    reads, with `complimentary_plus` true for the ids in `ids`."""

    def __init__(self, *ids: str, enabled: bool = True) -> None:
        self.ids = set(ids)
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def get_account(self, account_id: str):
        return Account(
            account_id=account_id,
            external_id=f"sub-{account_id}",
            created_at=NOW,
            complimentary_plus=account_id in self.ids,
        )


class _Clock:
    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def _billing(*, stripe: bool, complimentary: bool = True, included: int = 3, clock=None) -> _Billing:
    return _Billing(
        enabled=stripe,
        included=included,
        cap=5,
        clock=clock or (lambda: NOW),
        directory=_Flags(ACCOUNT) if complimentary else _Flags(),
    )


def _saving_pipeline(billing: _Billing) -> tuple[_Pipeline, InMemorySavedRuns, SavedHistory]:
    pipeline = _Pipeline(billing)
    saved = InMemorySavedRuns(SETTINGS)
    history = SavedHistory(runs=pipeline.runs, saved_runs=saved, plans=billing.plans)
    pipeline.process = ProcessRunUseCase(
        runs=pipeline.runs,
        media=pipeline.media,
        storage=pipeline.process._storage,
        analysis=pipeline.analysis,
        free_runs=pipeline.free_runs,
        account_free_runs=pipeline.account_runs,
        entitlements=pipeline.entitlements,
        extra_runs=billing.extra_runs,
        history=history,
    )
    return pipeline, saved, history


class StandingTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_flag_is_the_paid_plan_never_billable(self) -> None:
        for stripe in (False, True):
            with self.subTest(stripe=stripe):
                plan = await _billing(stripe=stripe).plans.standing(ACCOUNT)
                self.assertEqual((plan.paid, plan.complimentary, plan.billable), (True, True, False))
                self.assertIsNone(plan.subscription)

    async def test_a_real_subscription_wins(self) -> None:
        billing = _billing(stripe=True)
        await billing.subscribe()
        plan = await billing.plans.standing(ACCOUNT)
        self.assertEqual((plan.paid, plan.complimentary, plan.billable), (True, False, True))

    async def test_a_cancelled_subscription_falls_back_to_the_flag(self) -> None:
        billing = _billing(stripe=True)
        await billing.subscribe("canceled")
        plan = await billing.plans.standing(ACCOUNT)
        self.assertEqual((plan.paid, plan.complimentary), (True, True))

    async def test_no_flag_no_directory_or_no_store_is_the_free_plan(self) -> None:
        self.assertFalse((await _billing(stripe=False, complimentary=False).plans.standing(ACCOUNT)).paid)
        no_directory = _Billing(enabled=False)
        self.assertFalse((await no_directory.plans.standing(ACCOUNT)).paid)
        self.assertFalse(no_directory.plans.offered)
        off_store = _Billing(enabled=False, directory=_Flags(ACCOUNT, enabled=False))
        self.assertFalse((await off_store.plans.standing(ACCOUNT)).paid)
        self.assertFalse((await off_store.plans.standing(None)).paid)


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def _exhaust(self, pipeline: _Pipeline, billing: _Billing, *, already: int = 0) -> None:
        for _ in range(3 - already):
            await pipeline.intake()
        with self.assertRaises(FreeRunsExhaustedError) as caught:
            await pipeline.intake()
        error = caught.exception
        self.assertEqual((error.scope, error.period, error.limit, error.used), ("account", "day", 3, 3))
        self.assertIn("Plus runs", str(error))
        # Never an extra run: no ledger row, nothing reported, no customer.
        self.assertEqual(await billing.ledger.count(ACCOUNT, "2026-11"), 0)
        self.assertEqual(await billing.ledger.due(), [])
        self.assertEqual(billing.gateway.reported, [])
        self.assertEqual(billing.gateway.customers, [])

    async def test_stripe_off_gets_paid_limits_and_paid_daily_runs_then_402(self) -> None:
        billing = _billing(stripe=False)
        pipeline = _Pipeline(billing, spend_allowed=False)
        await pipeline.intake()
        limits = pipeline.queue.enqueued_limits[0]
        self.assertEqual(limits.tier, MediaTier.PAID)
        self.assertEqual((limits.max_duration_seconds, limits.max_file_size_mb), (600, 500))
        # The paid plan's daily counter and limit, not the free one (10),
        # and the shared daily cap (exhausted here) is not asked.
        self.assertEqual(pipeline.account_runs.consume_limits, [3])
        self.assertEqual(pipeline.account_runs.consume_periods, [FreeRunPeriod.DAY])
        self.assertEqual(pipeline.spend_cap.consume_calls, 0)
        await self._exhaust(pipeline, billing, already=1)

    async def test_stripe_on_is_refused_past_the_included_runs_too(self) -> None:
        billing = _billing(stripe=True)
        await self._exhaust(_Pipeline(billing, spend_allowed=False), billing)

    async def test_completed_runs_are_never_billed(self) -> None:
        billing = _billing(stripe=True)
        pipeline = _Pipeline(billing)
        for _ in range(3):
            run_id = await pipeline.run()
            self.assertEqual((await pipeline.runs.get(run_id)).status, RunStatus.COMPLETE)
            self.assertIsNone(billing.ledger.state(run_id))
        await billing.extra_runs.flush_due()
        self.assertEqual(billing.gateway.reported, [])

    async def test_byok_is_still_exempt(self) -> None:
        billing = _billing(stripe=False)
        pipeline = _Pipeline(billing)
        for _ in range(5):
            await pipeline.intake(key="user-key")
        self.assertEqual(pipeline.account_runs.consume_calls, 0)
        self.assertEqual(pipeline.queue.enqueued_limits[0].tier, MediaTier.PAID)

    async def test_a_real_subscription_plus_the_flag_gets_billed_extra_runs(self) -> None:
        billing = _billing(stripe=True)
        await billing.subscribe()
        pipeline = _Pipeline(billing, spend_allowed=False)
        for _ in range(3):
            await pipeline.intake()
        extra = await pipeline.intake()
        self.assertEqual(billing.ledger.state(extra), HELD)

    async def test_an_ordinary_free_account_is_unchanged(self) -> None:
        billing = _billing(stripe=False, complimentary=False)
        pipeline = _Pipeline(billing)
        for _ in range(10):
            await pipeline.intake()
        with self.assertRaises(FreeRunsExhaustedError) as caught:
            await pipeline.intake()
        self.assertIn("free runs", str(caught.exception))
        self.assertEqual(set(pipeline.account_runs.consume_limits), {None})
        self.assertEqual(pipeline.queue.enqueued_limits[0].tier, MediaTier.STANDARD)
        self.assertEqual(pipeline.spend_cap.consume_calls, 10)


class SavedHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_stripe_off_saves_and_lists_its_runs(self) -> None:
        billing = _billing(stripe=False)
        pipeline, saved, history = _saving_pipeline(billing)
        run_id = await pipeline.run()
        queries = SavedHistoryQueries(history=history)
        page = await queries.list(_person())
        self.assertEqual([item.run_id for item in page.items], [run_id])
        self.assertEqual((await queries.get(_person(), run_id)).title, "T")
        status = await history.status(ACCOUNT)
        self.assertEqual((status.saving, status.expires_at), (True, None))

    async def test_a_free_account_is_never_saved_and_shows_no_window(self) -> None:
        billing = _billing(stripe=False, complimentary=False)
        pipeline, saved, history = _saving_pipeline(billing)
        await pipeline.run()
        self.assertEqual(await saved.count(ACCOUNT), 0)
        # Stripe off: no window is shown or armed, as before.
        await saved.arm_expiry(ACCOUNT, NOW + timedelta(days=3))
        status = await history.status(ACCOUNT)
        self.assertEqual((status.saving, status.expires_at), (False, None))

    async def test_stripe_off_never_arms_or_purges_anyone(self) -> None:
        billing = _billing(stripe=False, complimentary=False)
        pipeline, saved, history = _saving_pipeline(billing)
        # Rows left from when Stripe was on: switching it off removes nothing.
        billing.plans._directory.ids.add(ACCOUNT)
        await pipeline.run()
        billing.plans._directory.ids.clear()
        self.assertEqual(await history.arm_lapsed(), 0)
        self.assertEqual(await history.purge_expired(), 0)
        self.assertEqual(await saved.count(ACCOUNT), 1)

    async def test_stripe_on_no_window_for_complimentary(self) -> None:
        clock = _Clock()
        billing = _billing(stripe=True, clock=clock)
        await billing.subscribe("canceled")
        pipeline, saved, history = _saving_pipeline(billing)
        history._clock = clock
        await pipeline.run()
        self.assertEqual(await saved.count(ACCOUNT), 1)
        # The cancelled subscription would arm the window; the flag keeps it off.
        await history.sync_expiry(ACCOUNT)
        self.assertEqual(await history.arm_lapsed(), 0)
        self.assertIsNone(await saved.expiry(ACCOUNT))
        # One armed before the flag was set is cleared, never purged.
        await saved.arm_expiry(ACCOUNT, clock.now - timedelta(days=1))
        self.assertEqual(await history.purge_expired(), 0)
        self.assertIsNone(await saved.expiry(ACCOUNT))
        self.assertEqual(await saved.count(ACCOUNT), 1)
        self.assertTrue((await history.status(ACCOUNT)).saving)


class RestoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_restore_leaves_the_flag_and_starts_no_window(self) -> None:
        clock = _Clock()
        directory = InMemoryAccountDirectory()
        account = await directory.resolve_account("sub-1")
        directory.set_complimentary_plus(account.account_id)
        billing = _Billing(enabled=True, clock=clock, directory=directory)
        runs = FakeRunRepository()
        saved = InMemorySavedRuns(SETTINGS, accounts=directory)
        history = SavedHistory(runs=runs, saved_runs=saved, plans=billing.plans, clock=clock)
        deleter = InMemoryAccountDeleter(
            SETTINGS,
            accounts=directory,
            api_keys=InMemoryApiKeyRepository(),
            billing_accounts=billing.accounts,
            saved_runs=saved,
        )
        await deleter.schedule_deletion("sub-1", now=clock.now, purge_at=clock.now + timedelta(days=30))
        person = Principal(
            subject="user:sub-1", authenticated=True, method=AuthMethod.TOKEN, account_id=account.account_id
        )
        self.assertTrue(await RestoreAccountUseCase(deleter=deleter, history=history, clock=clock).execute(person))
        self.assertTrue((await directory.get_account(account.account_id)).complimentary_plus)
        self.assertTrue((await billing.plans.standing(account.account_id)).complimentary)
        self.assertIsNone(await saved.expiry(account.account_id))


class ViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_billing_view_stripe_off(self) -> None:
        billing = _billing(stripe=False)
        pipeline = _Pipeline(billing)
        view = await GetBillingUseCase(plans=billing.plans, account_free_runs=pipeline.account_runs).execute(
            _person()
        )
        self.assertEqual((view.enabled, view.plan, view.complimentary), (False, "paid", True))
        self.assertEqual((view.runs_limit, view.runs_period), (3, "day"))
        self.assertIsNone(view.extra_runs)
        self.assertIsNone(view.prices)

    async def test_billing_view_stripe_on_and_ordinary(self) -> None:
        billing = _billing(stripe=True)
        runs = _Pipeline(billing).account_runs
        view = await GetBillingUseCase(plans=billing.plans, account_free_runs=runs).execute(_person())
        self.assertEqual((view.enabled, view.plan, view.complimentary), (True, "paid", True))
        self.assertIsNone(view.extra_runs)
        self.assertIsNotNone(view.prices)
        ordinary = _billing(stripe=False, complimentary=False)
        view = await GetBillingUseCase(plans=ordinary.plans, account_free_runs=runs).execute(_person())
        self.assertEqual((view.enabled, view.complimentary), (False, False))

    async def test_free_runs_and_me(self) -> None:
        billing = _billing(stripe=False)
        pipeline = _Pipeline(billing)
        standing = await GetFreeRunsUseCase(
            free_runs=FakeFreeRunAllowance(),
            device_tokens=FakeDeviceTokens(),
            account_free_runs=pipeline.account_runs,
            billing=billing.plans,
        ).standing("good:dev-a", _person())
        self.assertEqual((standing.plan, standing.overage, standing.complimentary), ("paid", False, True))
        self.assertEqual(standing.status.limit, 3)
        view = await GetAccountUseCase(
            accounts=InMemoryAccountDirectory(enabled=False), entitlements=pipeline.entitlements, billing=billing.plans
        ).execute(_person())
        self.assertEqual((view.entitlement.plan, view.entitlement.metered, view.complimentary), (Plan.PAID, False, True))
        self.assertEqual(view.entitlement.max_duration_seconds, 600)

    async def test_checkout_and_portal_refuse_without_touching_stripe(self) -> None:
        for stripe in (False, True):
            with self.subTest(stripe=stripe):
                billing = _billing(stripe=stripe)
                with self.assertRaises(ComplimentaryPlanError):
                    await StartCheckoutUseCase(plans=billing.plans).execute(_person(), "month")
                with self.assertRaises(ComplimentaryPlanError):
                    await OpenBillingPortalUseCase(plans=billing.plans).execute(_person())
                self.assertEqual((billing.gateway.customers, billing.gateway.checkouts), ([], []))
                self.assertEqual(billing.gateway.portals, [])
        ordinary = _billing(stripe=False, complimentary=False)
        with self.assertRaises(BillingNotConfiguredError):
            await StartCheckoutUseCase(plans=ordinary.plans).execute(_person(), "month")


if __name__ == "__main__":
    unittest.main()
