"""The paid plan (docs/backend/billing.md): checkout, portal, the billing
view, webhooks and subscription state, paid admission and extra runs,
billing on completion only, and account deletion cancelling the
subscription. Stripe is the FakeBillingGateway; the account link and the
ledger are the real in-memory adapters, so their rules are exercised too."""

import unittest
from datetime import datetime, timedelta, timezone

from app.application.billing import BillingPlans, ExtraRunBilling
from app.application.create_run import CreateRunUseCase
from app.application.delete_account import DeleteAccountUseCase
from app.application.entitlements import EntitlementResolver
from app.application.get_billing import GetBillingUseCase
from app.application.get_free_runs import GetFreeRunsUseCase
from app.application.get_run import GetRunUseCase
from app.application.handle_billing_webhook import HandleBillingWebhookUseCase
from app.application.open_billing_portal import OpenBillingPortalUseCase
from app.application.process_run import ProcessRunUseCase
from app.application.start_checkout import StartCheckoutUseCase
from app.domain.entitlements import MediaTier, Plan
from app.domain.entities import (
    AuthMethod,
    BillingWebhookEvent,
    FreeRunPeriod,
    Principal,
    RunStatus,
    SubscriptionSnapshot,
    VideoAnalysis,
)
from app.domain.errors import (
    AlreadySubscribedError,
    BillingIntervalError,
    BillingNotConfiguredError,
    BillingProviderError,
    ExtraRunsCapReachedError,
    ForbiddenError,
    FreeRunsExhaustedError,
    MediaValidationError,
    NoBillingAccountError,
    SubscriptionCancelFailedError,
    WebhookSignatureError,
)
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
from app.infrastructure.persistence.billing_store import (
    DUE,
    HELD,
    REPORTED,
    VOID,
    InMemoryBillingAccounts,
    InMemoryExtraRunLedger,
)

from .fakes import (
    FakeAccountDeleter,
    FakeAccountFreeRunAllowance,
    FakeAnalysisEngine,
    FakeBillingGateway,
    FakeDeviceTokens,
    FakeFreeRunAllowance,
    FakeJobQueue,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
    FakeSpendCap,
)

ACCOUNT = "acct-1"
CUSTOMER = f"cus_{ACCOUNT}"
URL = "https://x.test/v.mp4"
ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")
SETTINGS = Settings(_env_file=None, gemini_api_key="k")


def _person(account_id: str = ACCOUNT, method: AuthMethod = AuthMethod.TOKEN) -> Principal:
    return Principal(
        subject="user:sub-1", authenticated=True, method=method, account_id=account_id, email="a@b.test"
    )


def _future(days: int = 20) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _snapshot(status: str = "active", *, sub: str = "sub_1", customer: str = CUSTOMER, interval: str = "month", end=None):
    return SubscriptionSnapshot(
        subscription_id=sub,
        customer_id=customer,
        status=status,
        price_id="price_month" if interval == "month" else "price_year",
        interval=interval,
        current_period_end=end or _future(),
        cancel_at_period_end=False,
        account_id=ACCOUNT,
    )


class _Billing:
    """One deployment's worth of billing: gateway, stores, plans."""

    def __init__(
        self, *, enabled: bool = True, yearly: bool = True, cap: int = 200, included: int = 30, clock=None
    ) -> None:
        self.gateway = FakeBillingGateway(enabled=enabled, yearly=yearly)
        self.accounts = InMemoryBillingAccounts(SETTINGS)
        self.ledger = InMemoryExtraRunLedger(SETTINGS)
        self.plans = BillingPlans(
            gateway=self.gateway,
            accounts=self.accounts,
            ledger=self.ledger,
            paid_runs_per_day=included,
            extra_runs_monthly_cap=cap,
            clock=clock,
        )
        self.extra_runs = ExtraRunBilling(plans=self.plans)

    async def subscribe(self, status: str = "active", **kwargs) -> None:
        await self.accounts.link_customer(ACCOUNT, CUSTOMER)
        await self.accounts.apply_subscription(ACCOUNT, _snapshot(status, **kwargs))


class CheckoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.billing = _Billing()
        self.use_case = StartCheckoutUseCase(plans=self.billing.plans)

    async def test_creates_the_customer_once_and_returns_the_checkout_url(self) -> None:
        url = await self.use_case.execute(_person(), "month")
        self.assertEqual(url, f"https://checkout.stripe.test/{CUSTOMER}/month")
        # A second try (the first tab was closed) reuses the customer.
        await self.use_case.execute(_person(), "year")
        self.assertEqual(self.billing.gateway.customers, [CUSTOMER])
        self.assertEqual([c["interval"] for c in self.billing.gateway.checkouts], ["month", "year"])
        self.assertEqual((await self.billing.accounts.get(ACCOUNT)).stripe_customer_id, CUSTOMER)

    async def test_a_live_subscription_is_409(self) -> None:
        for status in ("active", "past_due", "trialing", "unpaid"):
            billing = _Billing()
            await billing.subscribe(status)
            with self.assertRaises(AlreadySubscribedError):
                await StartCheckoutUseCase(plans=billing.plans).execute(_person(), "month")
            self.assertEqual(billing.gateway.checkouts, [])

    async def test_a_cancelled_subscription_may_subscribe_again(self) -> None:
        await self.billing.subscribe("canceled")
        self.assertTrue(await self.use_case.execute(_person(), "month"))

    async def test_an_api_key_is_forbidden(self) -> None:
        with self.assertRaises(ForbiddenError):
            await self.use_case.execute(_person(method=AuthMethod.API_KEY), "month")
        self.assertEqual(self.billing.gateway.customers, [])

    async def test_intervals(self) -> None:
        with self.assertRaises(BillingIntervalError):
            await self.use_case.execute(_person(), "week")
        no_yearly = _Billing(yearly=False)
        with self.assertRaises(BillingIntervalError):
            await StartCheckoutUseCase(plans=no_yearly.plans).execute(_person(), "year")

    async def test_billing_off_is_refused(self) -> None:
        off = _Billing(enabled=False)
        with self.assertRaises(BillingNotConfiguredError):
            await StartCheckoutUseCase(plans=off.plans).execute(_person(), "month")

    async def test_stripe_down_is_a_provider_error(self) -> None:
        self.billing.gateway.error = BillingProviderError(log_detail="down")
        with self.assertRaises(BillingProviderError):
            await self.use_case.execute(_person(), "month")


class PortalTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_customer_is_404(self) -> None:
        billing = _Billing()
        with self.assertRaises(NoBillingAccountError):
            await OpenBillingPortalUseCase(plans=billing.plans).execute(_person())

    async def test_returns_the_portal_url(self) -> None:
        billing = _Billing()
        await billing.subscribe()
        url = await OpenBillingPortalUseCase(plans=billing.plans).execute(_person())
        self.assertEqual(url, f"https://billing.stripe.test/{CUSTOMER}")

    async def test_an_api_key_is_forbidden(self) -> None:
        billing = _Billing()
        await billing.subscribe()
        with self.assertRaises(ForbiddenError):
            await OpenBillingPortalUseCase(plans=billing.plans).execute(_person(method=AuthMethod.API_KEY))


class GetBillingTests(unittest.IsolatedAsyncioTestCase):
    async def test_off_is_just_disabled(self) -> None:
        view = await GetBillingUseCase(plans=_Billing(enabled=False).plans, account_free_runs=None).execute(_person())
        self.assertFalse(view.enabled)

    async def test_free_account(self) -> None:
        billing = _Billing()
        runs = FakeAccountFreeRunAllowance(limit=10)
        runs.counts[(ACCOUNT, runs.day)] = 3
        # A monthly row (one written before 2026-11-14) is not the free plan's.
        runs.counts[(ACCOUNT, runs.month)] = 7
        view = await GetBillingUseCase(plans=billing.plans, account_free_runs=runs).execute(_person())
        self.assertEqual((view.enabled, view.plan, view.status), (True, "free", None))
        self.assertEqual((view.runs_limit, view.runs_used, view.runs_period), (10, 3, "day"))
        self.assertEqual(view.prices.month.amount, 1200)

    async def test_paid_account_counts_against_the_plan(self) -> None:
        billing = _Billing()
        await billing.subscribe(interval="year")
        runs = FakeAccountFreeRunAllowance(limit=10)
        # A monthly row from before 2026-11-14 is no longer the paid plan's.
        runs.counts[(ACCOUNT, runs.month)] = 42
        runs.counts[(ACCOUNT, runs.day)] = 5
        view = await GetBillingUseCase(plans=billing.plans, account_free_runs=runs).execute(_person())
        self.assertEqual((view.plan, view.status, view.interval), ("paid", "active", "year"))
        self.assertEqual((view.runs_limit, view.runs_used, view.runs_period), (30, 5, "day"))

    async def test_past_due_reads_as_free(self) -> None:
        billing = _Billing()
        await billing.subscribe("past_due")
        view = await GetBillingUseCase(
            plans=billing.plans, account_free_runs=FakeAccountFreeRunAllowance(limit=10)
        ).execute(_person())
        self.assertEqual((view.plan, view.status, view.runs_limit), ("free", "past_due", 10))


class WebhookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.billing = _Billing()
        await self.billing.accounts.link_customer(ACCOUNT, CUSTOMER)
        self.use_case = HandleBillingWebhookUseCase(plans=self.billing.plans)

    def _event(self, signature: str, event_id: str, kind: str, *, sub: str = "sub_1", customer: str = CUSTOMER):
        self.billing.gateway.events[signature] = BillingWebhookEvent(
            event_id=event_id, type=kind, customer_id=customer, subscription_id=sub, account_id=ACCOUNT
        )

    async def test_a_bad_signature_reads_nothing(self) -> None:
        with self.assertRaises(WebhookSignatureError):
            await self.use_case.execute(b"{}", "forged")
        self.assertFalse(await self.billing.accounts.event_seen("evt_1"))

    async def test_billing_off_is_refused(self) -> None:
        with self.assertRaises(BillingNotConfiguredError):
            await HandleBillingWebhookUseCase(plans=_Billing(enabled=False).plans).execute(b"{}", "sig")

    async def test_checkout_completed_makes_the_account_paid(self) -> None:
        self.billing.gateway.subscriptions["sub_1"] = _snapshot()
        self._event("sig", "evt_1", "checkout.session.completed")
        self.assertEqual(await self.use_case.execute(b"{}", "sig"), "handled")
        self.assertIsNotNone(await self.billing.plans.paid_account(ACCOUNT))

    async def test_an_event_is_handled_once(self) -> None:
        self.billing.gateway.subscriptions["sub_1"] = _snapshot()
        self._event("sig", "evt_1", "customer.subscription.updated")
        await self.use_case.execute(b"{}", "sig")
        # Stripe resends it; meanwhile the subscription moved on.
        self.billing.gateway.subscriptions["sub_1"] = _snapshot("canceled")
        self.assertEqual(await self.use_case.execute(b"{}", "sig"), "duplicate")
        self.assertEqual((await self.billing.accounts.get(ACCOUNT)).status, "active")

    async def test_state_transitions_follow_stripe(self) -> None:
        steps = [
            ("customer.subscription.created", "active", True),
            ("invoice.payment_failed", "past_due", False),
            ("invoice.paid", "active", True),
            ("customer.subscription.deleted", "canceled", False),
        ]
        for index, (kind, status, paid) in enumerate(steps):
            self.billing.gateway.subscriptions["sub_1"] = _snapshot(status)
            self._event(f"sig{index}", f"evt_{index}", kind)
            await self.use_case.execute(b"{}", f"sig{index}")
            self.assertEqual((await self.billing.accounts.get(ACCOUNT)).status, status, kind)
            self.assertEqual(await self.billing.plans.paid_account(ACCOUNT) is not None, paid, kind)

    async def test_order_does_not_matter_the_subscription_is_refetched(self) -> None:
        # "updated" arrives after "deleted", but Stripe now says canceled.
        self.billing.gateway.subscriptions["sub_1"] = _snapshot("canceled")
        self._event("a", "evt_a", "customer.subscription.updated")
        await self.use_case.execute(b"{}", "a")
        self.assertIsNone(await self.billing.plans.paid_account(ACCOUNT))

    async def test_an_old_subscription_never_overwrites_the_live_one(self) -> None:
        self.billing.gateway.subscriptions["sub_new"] = _snapshot(sub="sub_new")
        self.billing.gateway.subscriptions["sub_old"] = _snapshot("canceled", sub="sub_old")
        self._event("new", "evt_new", "customer.subscription.created", sub="sub_new")
        self._event("old", "evt_old", "customer.subscription.deleted", sub="sub_old")
        await self.use_case.execute(b"{}", "new")
        await self.use_case.execute(b"{}", "old")
        row = await self.billing.accounts.get(ACCOUNT)
        self.assertEqual((row.stripe_subscription_id, row.status), ("sub_new", "active"))

    async def test_unknown_customers_and_foreign_subscriptions_are_ignored(self) -> None:
        self._event("u", "evt_u", "customer.subscription.updated", customer="cus_stranger")
        self.assertEqual(await self.use_case.execute(b"{}", "u"), "ignored")
        self.billing.gateway.subscriptions["sub_x"] = _snapshot(sub="sub_x", customer="cus_other")
        self._event("x", "evt_x", "customer.subscription.updated", sub="sub_x")
        self.assertEqual(await self.use_case.execute(b"{}", "x"), "ignored")
        self.assertIsNone((await self.billing.accounts.get(ACCOUNT)).status)

    async def test_unhandled_types_are_acknowledged(self) -> None:
        self._event("p", "evt_p", "payment_intent.created")
        self.assertEqual(await self.use_case.execute(b"{}", "p"), "ignored")
        self.assertTrue(await self.billing.accounts.event_seen("evt_p"))

    async def test_a_stripe_failure_is_retried_not_marked_seen(self) -> None:
        self._event("s", "evt_s", "customer.subscription.updated")
        self.billing.gateway.error = BillingProviderError(log_detail="down")
        with self.assertRaises(BillingProviderError):
            await self.use_case.execute(b"{}", "s")
        self.assertFalse(await self.billing.accounts.event_seen("evt_s"))


class _Pipeline:
    """Intake plus worker over shared fakes, with billing wired as in the
    container."""

    def __init__(self, billing: _Billing, *, spend_allowed: bool = True) -> None:
        self.billing = billing
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.analysis = FakeAnalysisEngine(result=ANALYSIS)
        self.spend_cap = FakeSpendCap(allow=spend_allowed)
        self.account_runs = FakeAccountFreeRunAllowance(limit=10)
        self.free_runs = FakeFreeRunAllowance()
        self.entitlements = EntitlementResolver(
            max_duration_seconds=180,
            max_file_size_mb=200,
            signed_in_byok_max_duration_seconds=600,
            signed_in_byok_max_file_size_mb=500,
        )
        self.queue = FakeJobQueue()
        self.create = CreateRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            queue=self.queue,
            spend_cap=self.spend_cap,
            free_runs=self.free_runs,
            device_tokens=FakeDeviceTokens(),
            distributed=False,
            account_free_runs=self.account_runs,
            entitlements=self.entitlements,
            billing=billing.plans,
        )
        self.process = ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            analysis=self.analysis,
            free_runs=self.free_runs,
            account_free_runs=self.account_runs,
            entitlements=self.entitlements,
            extra_runs=billing.extra_runs,
        )

    async def intake(self, key: str | None = None) -> str:
        run = await self.create.execute(
            principal=_person(),
            accept_terms=True,
            file=None,
            url=URL,
            gemini_api_key=key,
            device_token="good:dev-a",
            client_ip="1.1.1.1",
        )
        return run.run_id

    async def run(self, key: str | None = None) -> str:
        run_id = await self.intake(key)
        await self.process.execute(run_id, source_url=URL, gemini_api_key=key)
        return run_id

    def used(self, period: FreeRunPeriod = FreeRunPeriod.DAY) -> int:
        return self.account_runs.used(ACCOUNT, period)


class PaidAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.billing = _Billing(included=3, cap=2, clock=lambda: datetime(2026, 11, 14, 12, tzinfo=timezone.utc))
        await self.billing.subscribe()
        self.pipeline = _Pipeline(self.billing, spend_allowed=False)

    async def test_within_the_plan_counts_against_the_plan_limit(self) -> None:
        await self.pipeline.intake()
        self.assertEqual(self.pipeline.used(), 1)
        self.assertEqual(self.pipeline.account_runs.consume_limits, [3])
        # The paid plan's included runs count per UTC day (since 2026-11-14).
        self.assertEqual(self.pipeline.account_runs.consume_periods, [FreeRunPeriod.DAY])
        self.assertEqual(self.pipeline.used(FreeRunPeriod.MONTH), 0)
        # Not an extra run, and the daily cap (here: exhausted) is not asked.
        self.assertEqual(await self.billing.ledger.due(), [])
        self.assertEqual(self.pipeline.spend_cap.consume_calls, 0)

    async def test_a_monthly_row_from_before_the_switch_does_not_count(self) -> None:
        # The paid plan counted per month before 2026-11-14; that row is not read.
        self.pipeline.account_runs.counts[(ACCOUNT, self.pipeline.account_runs.month)] = 99
        within = [await self.pipeline.intake() for _ in range(3)]
        self.assertEqual([self.billing.ledger.state(run_id) for run_id in within], [None, None, None])

    async def test_upgrading_mid_day_counts_todays_free_runs_once(self) -> None:
        # Free plan earlier today: 2 runs on the daily row, which the paid
        # plan now counts on too, against its own limit (3 here).
        self.pipeline.account_runs.counts[(ACCOUNT, self.pipeline.account_runs.day)] = 2
        within = await self.pipeline.intake()
        self.assertIsNone(self.billing.ledger.state(within))
        self.assertEqual(self.billing.ledger.state(await self.pipeline.intake()), HELD)
        # Each run counted once: the one included run on the daily row.
        self.assertEqual(self.pipeline.used(), 3)

    async def test_downgrading_mid_day_keeps_todays_count(self) -> None:
        for _ in range(3):
            await self.pipeline.intake()
        await self.billing.subscribe("canceled")
        self.pipeline.spend_cap.allow = True  # the free plan asks the daily cap
        await self.pipeline.intake()
        # Same daily row, now against the free limit (10): 3 paid + 1 free.
        self.assertEqual(self.pipeline.account_runs.consume_periods[-1], FreeRunPeriod.DAY)
        self.assertEqual(self.pipeline.account_runs.consume_limits[-1], None)
        self.assertEqual(self.pipeline.used(), 4)

    async def test_included_runs_reset_daily_while_the_extra_run_cap_is_monthly(self) -> None:
        for _ in range(3):
            await self.pipeline.intake()
        first_extra = await self.pipeline.intake()
        self.assertEqual(self.billing.ledger.state(first_extra), HELD)
        # Next UTC day: the included runs are back...
        self.pipeline.account_runs.day = "2026-11-15"
        for _ in range(3):
            run_id = await self.pipeline.intake()
            self.assertIsNone(self.billing.ledger.state(run_id))
        # ...but the extra-run cap (2) still counts the month: one left.
        self.assertEqual(self.billing.ledger.state(await self.pipeline.intake()), HELD)
        self.assertEqual(await self.billing.ledger.count(ACCOUNT, "2026-11"), 2)
        with self.assertRaises(ExtraRunsCapReachedError):
            await self.pipeline.intake()

    async def test_over_the_limit_is_admitted_as_an_extra_run_then_capped(self) -> None:
        for _ in range(3):
            await self.pipeline.intake()
        extra = [await self.pipeline.intake() for _ in range(2)]
        self.assertEqual([self.billing.ledger.state(run_id) for run_id in extra], [HELD, HELD])
        self.assertEqual(self.pipeline.used(), 3)
        with self.assertRaises(ExtraRunsCapReachedError) as caught:
            await self.pipeline.intake()
        self.assertEqual(caught.exception.limit, 2)

    async def test_byok_is_never_counted_or_billed(self) -> None:
        for _ in range(5):
            await self.pipeline.run(key="user-key")
        self.assertEqual(self.pipeline.account_runs.consume_calls, 0)
        self.assertEqual(self.billing.gateway.reported, [])
        self.assertEqual(await self.billing.ledger.count(ACCOUNT, "2026-11"), 0)

    async def test_paid_runs_get_the_paid_media_tier_and_the_long_job(self) -> None:
        await self.pipeline.intake()
        limits = self.pipeline.queue.enqueued_limits[0]
        self.assertEqual(limits.tier, MediaTier.PAID)
        self.assertTrue(limits.tier.long_job)
        self.assertEqual((limits.max_duration_seconds, limits.max_file_size_mb), (600, 500))

    async def test_past_due_is_on_the_free_rules(self) -> None:
        billing = _Billing()
        await billing.subscribe("past_due")
        pipeline = _Pipeline(billing)
        for _ in range(10):
            await pipeline.intake()
        with self.assertRaises(FreeRunsExhaustedError):
            await pipeline.intake()
        self.assertEqual(set(pipeline.account_runs.consume_limits), {None})
        self.assertEqual(pipeline.queue.enqueued_limits[0].tier, MediaTier.STANDARD)

    async def test_an_expired_period_is_free_after_the_grace(self) -> None:
        billing = _Billing()
        await billing.subscribe(end=datetime.now(timezone.utc) - timedelta(days=4))
        self.assertIsNone(await billing.plans.paid_account(ACCOUNT))
        billing = _Billing()
        await billing.subscribe(end=datetime.now(timezone.utc) - timedelta(days=1))
        self.assertIsNotNone(await billing.plans.paid_account(ACCOUNT))


class ExtraRunBillingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.billing = _Billing(included=0)
        await self.billing.subscribe()
        self.pipeline = _Pipeline(self.billing)

    async def test_a_completed_extra_run_is_reported_once(self) -> None:
        run_id = await self.pipeline.run()
        self.assertEqual(self.pipeline.runs.runs[run_id].status, RunStatus.COMPLETE)
        self.assertEqual(self.billing.gateway.reported, [run_id])
        self.assertEqual(self.billing.ledger.state(run_id), REPORTED)
        # A retried job (arq max_tries) and a flush change nothing.
        await self.pipeline.process.execute(run_id, source_url=URL)
        await self.billing.extra_runs.flush_due()
        await self.billing.extra_runs.complete(run_id)
        self.assertEqual(self.billing.gateway.reported, [run_id])

    async def test_a_failed_run_is_never_billed(self) -> None:
        self.pipeline.media.download_error = MediaValidationError("This post isn't public.")
        run_id = await self.pipeline.run()
        self.assertEqual(self.pipeline.runs.runs[run_id].status, RunStatus.FAILED)
        self.assertEqual(self.billing.ledger.state(run_id), VOID)
        # Even if something later tried to complete it.
        self.assertIsNone(await self.billing.ledger.complete(run_id))
        await self.billing.extra_runs.flush_due()
        self.assertEqual(self.billing.gateway.reported, [])

    async def test_a_failure_at_analysis_is_not_billed_either(self) -> None:
        from app.domain.errors import AnalysisUnavailableError

        self.pipeline.analysis.error = AnalysisUnavailableError("Gemini is busy.")
        run_id = await self.pipeline.run()
        self.assertEqual(self.billing.ledger.state(run_id), VOID)
        self.assertEqual(self.billing.gateway.reported, [])

    async def test_a_report_failure_never_fails_the_run_and_is_flushed_later(self) -> None:
        self.billing.gateway.report_error = BillingProviderError(log_detail="down")
        run_id = await self.pipeline.run()
        self.assertEqual(self.pipeline.runs.runs[run_id].status, RunStatus.COMPLETE)
        self.assertEqual(self.billing.ledger.state(run_id), DUE)
        self.billing.gateway.report_error = None
        self.assertEqual(await self.billing.extra_runs.flush_due(), 1)
        self.assertEqual(self.billing.gateway.reported, [run_id])
        self.assertEqual(await self.billing.extra_runs.flush_due(), 0)

    async def test_a_run_the_stale_check_fails_is_voided(self) -> None:
        run_id = await self.pipeline.intake()
        self.pipeline.runs.runs[run_id].updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
        get_run = GetRunUseCase(
            runs=self.pipeline.runs,
            stale_after_seconds=60,
            long_stale_after_seconds=60,
            free_runs=self.pipeline.free_runs,
            account_free_runs=self.pipeline.account_runs,
            extra_runs=self.billing.extra_runs,
        )
        await get_run.execute(run_id, _person())
        self.assertEqual(self.pipeline.runs.runs[run_id].status, RunStatus.FAILED)
        self.assertEqual(self.billing.ledger.state(run_id), VOID)
        # The worker finishing late cannot bill it now.
        await self.billing.extra_runs.complete(run_id)
        self.assertEqual(self.billing.gateway.reported, [])


class PaidStandingTests(unittest.IsolatedAsyncioTestCase):
    async def test_free_runs_endpoint_shows_the_paid_plan(self) -> None:
        billing = _Billing()
        await billing.subscribe()
        runs = FakeAccountFreeRunAllowance(limit=10)
        runs.counts[(ACCOUNT, runs.month)] = 12
        runs.counts[(ACCOUNT, runs.day)] = 4
        use_case = GetFreeRunsUseCase(
            free_runs=FakeFreeRunAllowance(), device_tokens=FakeDeviceTokens(), account_free_runs=runs, billing=billing.plans
        )
        standing = await use_case.standing(None, _person())
        self.assertEqual((standing.plan, standing.overage), ("paid", True))
        self.assertEqual((standing.status.limit, standing.status.used, standing.status.remaining), (30, 4, 26))
        self.assertEqual(standing.status.period, FreeRunPeriod.DAY)
        self.assertEqual(standing.status.resets_at, datetime(2026, 11, 15, tzinfo=timezone.utc))

    async def test_anonymous_has_no_plan(self) -> None:
        use_case = GetFreeRunsUseCase(
            free_runs=FakeFreeRunAllowance(), device_tokens=FakeDeviceTokens(), billing=_Billing().plans
        )
        standing = await use_case.standing(None, Principal(subject="client:x", authenticated=False))
        self.assertIsNone(standing.plan)
        self.assertFalse(standing.overage)

    async def test_entitlement_says_paid(self) -> None:
        resolver = EntitlementResolver(
            max_duration_seconds=180,
            max_file_size_mb=200,
            signed_in_byok_max_duration_seconds=600,
            signed_in_byok_max_file_size_mb=500,
        )
        entitlement = await resolver.for_principal(_person(), paid=True)
        self.assertEqual(entitlement.plan, Plan.PAID)
        self.assertTrue(entitlement.metered)
        self.assertEqual(entitlement.max_duration_seconds, 600)


class DeletionCancelsTheSubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.log: list[str] = []
        self.directory = InMemoryAccountDirectory()
        account = await self.directory.resolve_account("sub-1", "a@b.test")
        self.person = Principal(
            subject="user:sub-1",
            authenticated=True,
            method=AuthMethod.TOKEN,
            account_id=account.account_id,
            workspace_id=account.default_workspace_id,
        )
        self.billing = _Billing()
        await self.billing.accounts.link_customer(account.account_id, CUSTOMER)
        await self.billing.accounts.apply_subscription(account.account_id, _snapshot())
        self.deleter = FakeAccountDeleter(self.log)

    def _use_case(self, billing: _Billing | None = None) -> DeleteAccountUseCase:
        return DeleteAccountUseCase(
            accounts=self.directory,
            deleter=self.deleter,
            api_keys=InMemoryApiKeyRepository(),
            runs=FakeRunRepository(),
            billing=(billing or self.billing).plans,
        )

    async def test_cancels_before_deleting_anything(self) -> None:
        await self._use_case().execute(self.person)
        self.assertEqual(self.billing.gateway.cancelled, ["sub_1"])
        self.assertEqual(self.log, ["rows:sub-1", "identity:sub-1"])

    async def test_due_extra_runs_are_reported_first(self) -> None:
        await self.billing.ledger.hold("run-x", account_id=self.person.account_id, customer_id=CUSTOMER, period="2026-11")
        await self.billing.ledger.complete("run-x")
        await self._use_case().execute(self.person)
        self.assertEqual(self.billing.gateway.reported, ["run-x"])

    async def test_refuses_when_stripe_fails_and_deletes_nothing(self) -> None:
        self.billing.gateway.cancel_error = BillingProviderError(log_detail="down")
        with self.assertRaises(SubscriptionCancelFailedError):
            await self._use_case().execute(self.person)
        self.assertEqual(self.log, [])

    async def test_refuses_when_billing_was_switched_off_with_a_live_subscription(self) -> None:
        off = _Billing(enabled=False)
        await off.accounts.link_customer(self.person.account_id, CUSTOMER)
        await off.accounts.apply_subscription(self.person.account_id, _snapshot())
        with self.assertRaises(SubscriptionCancelFailedError):
            await self._use_case(off).execute(self.person)
        self.assertEqual(self.log, [])

    async def test_no_subscription_deletes_as_before(self) -> None:
        fresh = _Billing()
        await self._use_case(fresh).execute(self.person)
        self.assertEqual(fresh.gateway.cancelled, [])
        self.assertEqual(self.log, ["rows:sub-1", "identity:sub-1"])


class BillingOffParityTests(unittest.IsolatedAsyncioTestCase):
    """With billing off, a signed-in account is on exactly the free rules,
    even with a subscription row left over."""

    async def test_admission_is_the_free_rule(self) -> None:
        billing = _Billing(enabled=False)
        await billing.subscribe()
        pipeline = _Pipeline(billing)
        for _ in range(10):
            await pipeline.run()
        with self.assertRaises(FreeRunsExhaustedError):
            await pipeline.intake()
        self.assertEqual(billing.gateway.reported, [])
        self.assertEqual(set(pipeline.account_runs.consume_limits), {None})
        self.assertIsNone(await billing.plans.paid_account(ACCOUNT))


if __name__ == "__main__":
    unittest.main()
