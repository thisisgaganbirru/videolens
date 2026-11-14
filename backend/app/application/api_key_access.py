"""The shared gate in front of every API-key operation: which workspace the
caller may manage keys for, if any. Used by the create, list and revoke use
cases so the rule is written once."""

from ..domain.entities import AuthMethod, Principal, WorkspaceRole
from ..domain.errors import AccountsNotConfiguredError, ForbiddenError
from ..domain.ports import AccountDirectory

DEFAULT_SCOPES = ["runs:write", "runs:read"]


async def key_workspace(principal: Principal, accounts: AccountDirectory, *, owner_only: bool) -> str:
    # Defence in depth behind the route's `require_person`: a leaked agent
    # key must never be able to mint more keys, whatever route reaches here.
    if principal.method is not AuthMethod.TOKEN:
        raise ForbiddenError("API keys can only be managed from a signed-in session.")
    if not accounts.enabled or not principal.workspace_id or not principal.account_id:
        raise AccountsNotConfiguredError("Accounts are not available on this server.")
    if owner_only:
        role = await accounts.member_role(principal.workspace_id, principal.account_id)
        if role != WorkspaceRole.OWNER.value:
            raise ForbiddenError("Only the workspace owner can create or revoke API keys.")
    return principal.workspace_id
