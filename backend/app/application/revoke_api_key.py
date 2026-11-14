from ..domain.entities import Principal
from ..domain.errors import ApiKeyNotFoundError
from ..domain.ports import AccountDirectory, ApiKeyRepository
from .api_key_access import key_workspace


class RevokeApiKeyUseCase:
    """Revokes one live key in the caller's workspace. A key from another
    workspace is "not found", never "forbidden", so ids do not leak."""

    def __init__(self, *, api_keys: ApiKeyRepository, accounts: AccountDirectory) -> None:
        self._api_keys = api_keys
        self._accounts = accounts

    async def execute(self, principal: Principal, key_id: str) -> None:
        workspace_id = await key_workspace(principal, self._accounts, owner_only=True)
        if not await self._api_keys.revoke(workspace_id, key_id):
            raise ApiKeyNotFoundError("API key not found.")
