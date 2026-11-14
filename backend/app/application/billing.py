"""The paid plan's shared rules (docs/backend/billing.md).

`BillingPlans` answers "is this account on the paid plan right now" for
admission, `GET /api/free-runs`, `GET /api/me` and `GET /api/billing`.
`ExtraRunBilling` moves a run past the included ones through the ledger
(held -> due -> reported, or held -> void) and reports it to Stripe once,
only after the run completed. Neither ever fails a run: billing bookkeeping
is logged and swallowed, exactly like the free-run refunds.
"""

import logging
from datetime import datetime, timezone
from typing import Callable

from ..domain.entities import BillingAccount, ExtraRunCharge
from ..domain.policies import subscription_grants_paid
from ..domain.ports import BillingAccounts, BillingGateway, ExtraRunLedger

logger = logging.getLogger("videolens")

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BillingPlans:
    def __init__(
        self,
        *,
        gateway: BillingGateway,
        accounts: BillingAccounts,
        ledger: ExtraRunLedger,
        paid_runs_per_month: int,
        extra_runs_monthly_cap: int = 0,
        clock: Clock | None = None,
    ) -> None:
        self.gateway = gateway
        self.accounts = accounts
        self.ledger = ledger
        self.paid_runs_per_month = max(0, paid_runs_per_month)
        self.extra_runs_monthly_cap = extra_runs_monthly_cap
        self._clock = clock or _utcnow

    @property
    def enabled(self) -> bool:
        """Stripe configured and somewhere to keep the account's link. Off =
        every caller is on the free rules, exactly as before billing."""
        return self.gateway.enabled and self.accounts.enabled

    def now(self) -> datetime:
        return self._clock()

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
