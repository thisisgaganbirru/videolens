"""What `GET /api/me` answers: who you are, which workspace you act in, and
what you are allowed to do. The plan is "paid" while the account holds an
active subscription (docs/backend/billing.md); usage is `GET /api/billing`."""

from dataclasses import dataclass

from ..domain.entities import Principal, SavedHistoryStatus, Workspace
from ..domain.entitlements import Entitlement
from ..domain.ports import AccountDirectory
from .billing import BillingPlans
from .entitlements import EntitlementResolver
from .saved_history import SavedHistory


@dataclass(frozen=True)
class AccountView:
    principal: Principal
    workspace: Workspace | None
    entitlement: Entitlement
    accounts_enabled: bool
    # Whether runs are being saved server-side, and when saved runs expire
    # after the paid plan ended (docs/backend/saved-history.md).
    saved_history: SavedHistoryStatus = SavedHistoryStatus()


class GetAccountUseCase:
    def __init__(
        self,
        *,
        accounts: AccountDirectory,
        entitlements: EntitlementResolver,
        billing: BillingPlans | None = None,
        history: SavedHistory | None = None,
    ) -> None:
        self._accounts = accounts
        self._entitlements = entitlements
        self._billing = billing
        self._history = history

    async def execute(self, principal: Principal) -> AccountView:
        workspace = None
        if self._accounts.enabled and principal.workspace_id:
            workspace = await self._accounts.get_workspace(principal.workspace_id)
        return AccountView(
            principal=principal,
            workspace=workspace,
            entitlement=await self._entitlements.for_principal(principal, paid=await self._is_paid(principal)),
            accounts_enabled=self._accounts.enabled,
            saved_history=(
                await self._history.status(principal.account_id)
                if self._history is not None and principal.authenticated
                else SavedHistoryStatus()
            ),
        )

    async def _is_paid(self, principal: Principal) -> bool:
        if self._billing is None or not principal.authenticated:
            return False
        return await self._billing.paid_account(principal.account_id) is not None
