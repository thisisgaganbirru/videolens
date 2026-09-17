"""What the account panel shows: who you are, which workspace you are in,
and how much of your plan is left."""

from dataclasses import dataclass

from ..domain.entities import Principal, UsageSummary, Workspace
from ..domain.ports import AccountDirectory, BillingGateway
from .entitlements import EntitlementResolver


@dataclass(frozen=True)
class AccountView:
    principal: Principal
    workspace: Workspace | None
    usage: UsageSummary
    billing_enabled: bool
    accounts_enabled: bool


class GetAccountUseCase:
    def __init__(
        self,
        *,
        accounts: AccountDirectory,
        billing: BillingGateway,
        entitlements: EntitlementResolver,
    ) -> None:
        self._accounts = accounts
        self._billing = billing
        self._entitlements = entitlements

    async def execute(self, principal: Principal) -> AccountView:
        workspace = await self._entitlements.workspace_for(principal)
        usage = await self._entitlements.usage_summary(principal)
        return AccountView(
            principal=principal,
            workspace=workspace,
            usage=usage,
            billing_enabled=self._billing.enabled,
            accounts_enabled=self._accounts.enabled,
        )
