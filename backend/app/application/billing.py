"""The paid plan's shared rules (docs/backend/billing.md).

`BillingPlans` answers "is this account on the paid plan right now" for
admission, `GET /api/free-runs`, `GET /api/me`, `GET /api/billing` and
saved history (`standing`): through a paying Stripe subscription, or through
complimentary Plus (`accounts.complimentary_plus`, set by hand in SQL by the
owner), which needs no Stripe and is never billed.
`ExtraRunBilling` moves a run past the included ones through the ledger
(held -> due -> reported, or held -> void) and reports it to Stripe once,
only after the run completed. Neither ever fails a run: billing bookkeeping
is logged and swallowed, exactly like the free-run refunds.
"""

import logging
from datetime import datetime, timezone
from typing import Callable

from ..domain.entities import BillingAccount, ExtraRunCharge, FreeRunPeriod, PlanStanding
from ..domain.policies import start_of_next_utc_month, subscription_grants_paid, utc_month
from ..domain.ports import AccountDirectory, BillingAccounts, BillingGateway, ExtraRunLedger

logger = logging.getLogger("videolens")

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BillingPlans:
    # The period the paid plan's included runs count over (the account
    # counter's key, "YYYY-MM-DD": a UTC day since 2026-11-14, it was the
    # month). One place to change it: admission, GET /api/free-runs and
    # GET /api/billing all read it from here. The extra-run ledger and its
    # cap stay per month regardless (Stripe bills the meter monthly).
    PAID_RUNS_PERIOD = FreeRunPeriod.DAY

    def __init__(
        self,
        *,
        gateway: BillingGateway,
        accounts: BillingAccounts,
        ledger: ExtraRunLedger,
        paid_runs_per_day: int,
        extra_runs_monthly_cap: int = 0,
        directory: AccountDirectory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.gateway = gateway
        # Where `accounts.complimentary_plus` is read. None (the container
        # passes None without a database) = nobody is complimentary.
        self._directory = directory
        self.accounts = accounts
        self.ledger = ledger
        self.paid_runs_per_day = max(0, paid_runs_per_day)
        self.paid_runs_period = self.PAID_RUNS_PERIOD
        self.extra_runs_monthly_cap = extra_runs_monthly_cap
        self._clock = clock or _utcnow

    @property
    def enabled(self) -> bool:
        """Stripe configured and somewhere to keep the account's link. Off =
        every caller is on the free rules, exactly as before billing."""
        return self.gateway.enabled and self.accounts.enabled

    @property
    def complimentary_enabled(self) -> bool:
        """An account store to read `complimentary_plus` from."""
        return self._directory is not None and self._directory.enabled

    @property
    def offered(self) -> bool:
        """Anyone can be on the paid plan on this deployment: Stripe billing
        is on, or complimentary Plus can be read. What saved history's
        saving gate asks; `enabled` stays "Stripe billing is on"."""
        return self.enabled or self.complimentary_enabled

    def now(self) -> datetime:
        return self._clock()

    def extra_runs_period(self, now: datetime | None = None) -> str:
        """The ledger period extra runs and their cap count against: the
        UTC month ("YYYY-MM"), whatever the included runs' period is."""
        return utc_month(now or self._clock())

    def extra_runs_resets_at(self, now: datetime | None = None) -> datetime:
        """When this month's extra-run count (and so the cap) starts over."""
        return start_of_next_utc_month(now or self._clock())

    async def extra_runs_used(self, account_id: str, period: str | None = None) -> int:
        """Extra runs this account has taken in `period` (default: this
        month). The one definition of "used" for both the safety cap at
        admission and `GET /api/billing`: every ledger row not voided, so
        held (in flight), due (completed, not yet reported) and reported."""
        return await self.ledger.count(account_id, period or self.extra_runs_period())

    async def paid_account(self, account_id: str | None) -> BillingAccount | None:
        """The account's billing row when it is on the paid plan now
        (active or trialing, within its period plus a short grace), else
        None. past_due, unpaid and canceled read as the free plan."""
        if not account_id or not self.enabled:
            return None
        account = await self.accounts.get(account_id)
        if account is None:
            return None
        if not subscription_grants_paid(account.status, account.current_period_end, self._clock()):
            return None
        return account

    async def is_complimentary(self, account_id: str | None) -> bool:
        """`accounts.complimentary_plus` for this account (False without an
        account store or for an unknown account). Says nothing about a
        subscription; `standing` combines the two."""
        if not account_id or not self.complimentary_enabled:
            return False
        assert self._directory is not None
        account = await self._directory.get_account(account_id)
        return bool(account is not None and account.complimentary_plus)

    async def standing(self, account_id: str | None) -> PlanStanding:
        """The plan this account is on now. A paying subscription wins (it
        is what billing follows); otherwise the complimentary flag puts the
        account on the paid plan, never billed; otherwise the free plan."""
        if not account_id:
            return PlanStanding()
        subscription = await self.paid_account(account_id)
        if subscription is not None:
            return PlanStanding(subscription=subscription)
        if await self.is_complimentary(account_id):
            return PlanStanding(complimentary=True)
        return PlanStanding()


class ExtraRunBilling:
    """Reports completed extra runs. Exactly once per run: the ledger moves a
    row held -> due in one conditional write, only that caller reports it,
    and the meter event's identifier is the run id, so a resend after a
    crash between "sent" and "marked reported" is dropped by Stripe."""

    def __init__(self, *, plans: BillingPlans) -> None:
        self._plans = plans

    @property
    def enabled(self) -> bool:
        return self._plans.enabled

    async def complete(self, run_id: str) -> None:
        """The run completed and its result is stored: bill it if it was an
        extra run. Never raises."""
        if not self.enabled:
            return
        try:
            charge = await self._plans.ledger.complete(run_id)
        except Exception:  # noqa: BLE001 - never fail a finished run over billing
            logger.exception("Could not settle the extra run for run %s", run_id)
            return
        if charge is None:
            return
        await self._report(charge)

    async def void(self, run_id: str) -> None:
        """The run failed, was refunded or was rejected: never bill it.
        A no-op for a run that is not a held extra run (or already due)."""
        if not self.enabled:
            return
        try:
            if await self._plans.ledger.void(run_id):
                logger.info("Run %s did not complete, so its extra run will not be billed", run_id)
        except Exception:  # noqa: BLE001 - the hold is pruned on its own
            logger.exception("Could not void the extra run for run %s", run_id)

    async def flush_due(self, *, limit: int = 50) -> int:
        """Report completed extra runs a previous attempt could not (Stripe
        down, worker restarted). Run by the worker's cron. Returns how many
        were reported."""
        if not self.enabled:
            return 0
        try:
            charges = await self._plans.ledger.due(limit=limit)
        except Exception:  # noqa: BLE001
            logger.exception("Could not read the extra runs waiting to be reported")
            return 0
        reported = 0
        for charge in charges:
            if await self._report(charge):
                reported += 1
        return reported

    async def _report(self, charge: ExtraRunCharge) -> bool:
        try:
            await self._plans.gateway.report_extra_run(charge)
        except Exception:  # noqa: BLE001 - left `due`; the cron retries it
            logger.exception("Could not report extra run %s to Stripe; it will be retried", charge.run_id)
            return False
        try:
            await self._plans.ledger.mark_reported(charge.run_id)
        except Exception:  # noqa: BLE001 - a resend is deduplicated by Stripe
            logger.exception("Reported extra run %s but could not record it", charge.run_id)
        logger.info("Run %s billed as an extra run (account %s)", charge.run_id, charge.account_id)
        return True
