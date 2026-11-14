"""What `GET /api/me` answers: who you are, which workspace you act in, and
what you are allowed to do. No usage in this phase; nothing is metered."""

from dataclasses import dataclass

from ..domain.entities import Principal, Workspace
from ..domain.entitlements import Entitlement
from ..domain.ports import AccountDirectory
from .entitlements import EntitlementResolver


@dataclass(frozen=True)
class AccountView:
    principal: Principal
    workspace: Workspace | None
    entitlement: Entitlement
    accounts_enabled: bool


class GetAccountUseCase:
    def __init__(self, *, accounts: AccountDirectory, entitlements: EntitlementResolver) -> None:
        self._accounts = accounts
        self._entitlements = entitlements

    async def execute(self, principal: Principal) -> AccountView:
        workspace = None
        if self._accounts.enabled and principal.workspace_id:
            workspace = await self._accounts.get_workspace(principal.workspace_id)
        return AccountView(
            principal=principal,
            workspace=workspace,
            entitlement=await self._entitlements.for_principal(principal),
            accounts_enabled=self._accounts.enabled,
        )
