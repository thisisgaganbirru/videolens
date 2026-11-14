"""`GET /api/billing`: where a signed-in account stands on the paid plan.

`enabled` keeps meaning "Stripe billing is on here" (checkout can be
offered). A complimentary Plus account gets the full answer even with it
off (`enabled: false`, `plan: "paid"`, `complimentary: true`), so the client
can show Plus and hide checkout and the portal; anyone else with billing
off gets just `enabled: false`, as before."""

from dataclasses import dataclass
from datetime import datetime

from ..domain.entities import BillingPrices, FreeRunPeriod, PlanStanding, Principal
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
    # Paid plan through a subscription only (None otherwise, complimentary
    # Plus included): billed extra runs this UTC month.
    extra_runs: "ExtraRunsView | None" = None
    # On the paid plan through complimentary Plus, not a paying subscription.
    complimentary: bool = False


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
        if not account_id or not self._plans.offered:
            return BillingView(enabled=False)
        plan: PlanStanding = await self._plans.standing(account_id)
        stripe_on = self._plans.enabled
        if not stripe_on and not plan.complimentary:
            return BillingView(enabled=False)
        # The Stripe row only while Stripe is on: with it off, a row left
        # from an earlier subscription says nothing true about today.
        account = await self._plans.accounts.get(account_id) if stripe_on else None
        # The plan's own counter: the paid plan's included runs today, or the
        # free plan's runs today (the same daily row, the plan's own limit;
        # docs/backend/free-runs.md).
        if plan.paid:
            limit, period = self._plans.paid_runs_per_day, self._plans.paid_runs_period
        else:
            limit, period = None, FreeRunPeriod.DAY
        used, shown_limit = 0, 0
        if self._account_free_runs is not None:
            status = await self._account_free_runs.status(account_id, limit=limit, period=period)
            used, shown_limit = status.used, status.limit
        extra_runs = None
        if plan.billable:
            now = self._plans.now()
            cap = self._plans.extra_runs_monthly_cap
            extra_runs = ExtraRunsView(
                used=await self._plans.extra_runs_used(account_id, self._plans.extra_runs_period(now)),
                limit=cap if cap > 0 else None,
                resets_at=self._plans.extra_runs_resets_at(now),
            )
        return BillingView(
            enabled=stripe_on,
            plan="paid" if plan.paid else "free",
            status=account.status if account is not None else None,
            interval=account.interval if account is not None else None,
            current_period_end=account.current_period_end if account is not None else None,
            cancel_at_period_end=bool(account.cancel_at_period_end) if account is not None else False,
            runs_limit=shown_limit,
            runs_used=used,
            runs_period=period.value,
            prices=await self._plans.gateway.prices() if stripe_on else None,
            extra_runs=extra_runs,
            complimentary=plan.complimentary,
        )
