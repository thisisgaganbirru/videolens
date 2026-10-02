"""Issuing, listing and revoking a workspace's API keys."""

from ..domain.entities import ApiKey, IssuedApiKey, Principal, WorkspaceRole
from ..domain.errors import ApiKeyNotFoundError, PermissionDeniedError, WorkspaceNotFoundError
from ..domain.ports import AccountDirectory, ApiKeyRepository
from .entitlements import EntitlementResolver

DEFAULT_SCOPES = ["runs:write", "runs:read"]
MAX_ACTIVE_KEYS = 10


class ManageApiKeysUseCase:
    def __init__(
        self,
        *,
        api_keys: ApiKeyRepository,
        accounts: AccountDirectory,
        entitlements: EntitlementResolver,
    ) -> None:
        self._api_keys = api_keys
        self._accounts = accounts
        self._entitlements = entitlements

    async def _workspace_id(self, principal: Principal, *, owner_only: bool) -> str:
        if not self._accounts.enabled or not principal.workspace_id or not principal.account_id:
            raise WorkspaceNotFoundError("Sign in to manage API keys.")
        entitlement = await self._entitlements.for_principal(principal)
        if not entitlement.api_access:
            raise PermissionDeniedError("API access is included with the Studio and Scale plans.")
        if owner_only:
            role = await self._accounts.member_role(principal.workspace_id, principal.account_id)
            if role != WorkspaceRole.OWNER.value:
                raise PermissionDeniedError("Only the workspace owner can create or revoke API keys.")
        return principal.workspace_id

    async def issue(self, principal: Principal, name: str) -> IssuedApiKey:
        workspace_id = await self._workspace_id(principal, owner_only=True)
        active = [key for key in await self._api_keys.list_for_workspace(workspace_id) if key.active]
        if len(active) >= MAX_ACTIVE_KEYS:
            raise PermissionDeniedError(f"A workspace can hold at most {MAX_ACTIVE_KEYS} active keys.")
        label = name.strip() or "Unnamed key"
        return await self._api_keys.issue(workspace_id, label[:80], list(DEFAULT_SCOPES))

    async def list(self, principal: Principal) -> list[ApiKey]:
        workspace_id = await self._workspace_id(principal, owner_only=False)
        return await self._api_keys.list_for_workspace(workspace_id)

    async def revoke(self, principal: Principal, key_id: str) -> None:
        workspace_id = await self._workspace_id(principal, owner_only=True)
        if not await self._api_keys.revoke(workspace_id, key_id):
            raise ApiKeyNotFoundError("API key not found.")
