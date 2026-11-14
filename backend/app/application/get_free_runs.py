from dataclasses import dataclass

from ..domain.entities import FreeRunPeriod, FreeRunStatus, Principal
from ..domain.ports import AccountFreeRunAllowance, DeviceTokenSigner, FreeRunAllowance
from .billing import BillingPlans


@dataclass(frozen=True)
class FreeRunStanding:
    """`GET /api/free-runs`. `plan` is None for an anonymous caller, so the
    route leaves the field out for them exactly as before; "free" or "paid"
    for a signed-in account. `overage`: runs past `limit` are billed
    as extra runs instead of refused (the paid plan)."""

    device_token: str
    status: FreeRunStatus
    plan: str | None = None
    overage: bool = False


class GetFreeRunsUseCase:
    """Tells a caller how many free runs it has left: a signed-in account
    today's account runs (when that allowance is on), anyone else this
    device's runs for today. A paid account sees its included runs
    today (`PAID_RUNS_PER_DAY`) instead (docs/backend/billing.md). `status.period` says which. Issues a device token first if
    the caller has none (or one this server didn't sign), signed in or not,
    so a person who signs out still holds a token.

    Read-only by contract: asking never spends a run. Issuing a token is
    free and stateless - nothing is stored until a run is actually taken.
    """

    def __init__(
        self,
        *,
        free_runs: FreeRunAllowance,
        device_tokens: DeviceTokenSigner,
        account_free_runs: AccountFreeRunAllowance | None = None,
        billing: BillingPlans | None = None,
    ) -> None:
        self._free_runs = free_runs
        self._device_tokens = device_tokens
        self._account_free_runs = account_free_runs
        self._billing = billing

    async def execute(
        self, device_token: str | None, principal: Principal | None = None
    ) -> tuple[str, FreeRunStatus]:
        standing = await self.standing(device_token, principal)
        return standing.device_token, standing.status

    async def standing(self, device_token: str | None, principal: Principal | None = None) -> FreeRunStanding:
        token = (device_token or "").strip()
        device_id = self._device_tokens.verify(token)
        if device_id is None:
            token = self._device_tokens.issue()
            device_id = self._device_tokens.verify(token)
            assert device_id is not None
        accounts = self._account_free_runs
        signed_in = (
            principal is not None and principal.authenticated and principal.account_id and accounts is not None
        )
        if signed_in:
            assert principal is not None and accounts is not None and principal.account_id
            # Same rules as CreateRunUseCase._admit, so the number shown is
            # the counter a run would be taken from.
            paid = await self._billing.paid_account(principal.account_id) if self._billing is not None else None
            if paid is not None:
                status = await accounts.status(
                    principal.account_id,
                    limit=self._billing.paid_runs_per_day,
                    period=self._billing.paid_runs_period,
                )
                return FreeRunStanding(token, status, plan="paid", overage=True)
            if accounts.enabled:
                status = await accounts.status(principal.account_id, period=FreeRunPeriod.DAY)
                return FreeRunStanding(token, status, plan="free")
        # Signed in with the account allowance off: the device rule, still
        # on the free plan.
        return FreeRunStanding(
            token, await self._free_runs.status(device_id), plan="free" if signed_in else None
        )
