"""`GET /api/billing`: where a signed-in account stands on the paid plan."""

from dataclasses import dataclass
from datetime import datetime

from ..domain.entities import BillingPrices, FreeRunPeriod, Principal
from ..domain.ports import AccountFreeRunAllowance
from .billing import BillingPlans


@dataclass(frozen=True)
class BillingView:
    enabled: bool
    plan: str = "free"
    status: str | None = None
    interval: str | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    runs_limit: int = 0
    runs_used: int = 0
    # The counter `runs_limit`/`runs_used` are for: "day" on both plans
    # since 2026-11-14.
    runs_period: str = FreeRunPeriod.DAY.value
    prices: BillingPrices | None = None
    # Paid plan only (None otherwise): billed extra runs this UTC month.
    extra_runs: "ExtraRunsView | None" = None


@dataclass(frozen=True)
class ExtraRunsView:
    """Extra runs this UTC month, counted exactly as the safety cap counts
    them (`BillingPlans.extra_runs_used`). `limit` is
    `PAID_EXTRA_RUNS_MONTHLY_CAP`, or None when the cap is off (0)."""

    used: int
    limit: int | None
    resets_at: datetime
    period: str = "month"


class GetBillingUseCase:
    def __init__(self, *, plans: BillingPlans, account_free_runs: AccountFreeRunAllowance | None) -> None:
        self._plans = plans
        self._account_free_runs = account_free_runs

    async def execute(self, principal: Principal) -> BillingView:
        account_id = principal.account_id
        if not self._plans.enabled or not account_id:
            return BillingView(enabled=False)
        account = await self._plans.accounts.get(account_id)
        paid = await self._plans.paid_account(account_id)
        # The plan's own counter: the paid plan's included runs today, or the
        # free plan's runs today (the same daily row, the plan's own limit;
        # docs/backend/free-runs.md).
        if paid is not None:
            limit, period = self._plans.paid_runs_per_day, self._plans.paid_runs_period
        else:
            limit, period = None, FreeRunPeriod.DAY
        used, shown_limit = 0, 0
        if self._account_free_runs is not None:
            status = await self._account_free_runs.status(account_id, limit=limit, period=period)
            used, shown_limit = status.used, status.limit
        extra_runs = None
        if paid is not None:
            now = self._plans.now()
            cap = self._plans.extra_runs_monthly_cap
            extra_runs = ExtraRunsView(
                used=await self._plans.extra_runs_used(account_id, self._plans.extra_runs_period(now)),
                limit=cap if cap > 0 else None,
                resets_at=self._plans.extra_runs_resets_at(now),
            )
        return BillingView(
            enabled=True,
            plan="paid" if paid is not None else "free",
            status=account.status if account is not None else None,
            interval=account.interval if account is not None else None,
            current_period_end=account.current_period_end if account is not None else None,
            cancel_at_period_end=bool(account.cancel_at_period_end) if account is not None else False,
            runs_limit=shown_limit,
            runs_used=used,
            runs_period=period.value,
            prices=await self._plans.gateway.prices(),
            extra_runs=extra_runs,
        )
