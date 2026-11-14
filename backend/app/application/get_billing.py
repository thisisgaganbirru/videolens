"""`GET /api/billing`: where a signed-in account stands on the paid plan."""

from dataclasses import dataclass
from datetime import datetime

from ..domain.entities import BillingPrices, Principal
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
    prices: BillingPrices | None = None


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
        # Included runs and free runs share one counter per month; the limit
        # shown is the plan's.
        limit = self._plans.paid_runs_per_month if paid is not None else None
        used, shown_limit = 0, 0
        if self._account_free_runs is not None:
            status = await self._account_free_runs.status(account_id, limit=limit)
            used, shown_limit = status.used, status.limit
        return BillingView(
            enabled=True,
            plan="paid" if paid is not None else "free",
            status=account.status if account is not None else None,
            interval=account.interval if account is not None else None,
            current_period_end=account.current_period_end if account is not None else None,
            cancel_at_period_end=bool(account.cancel_at_period_end) if account is not None else False,
            runs_limit=shown_limit,
            runs_used=used,
            prices=await self._plans.gateway.prices(),
        )
