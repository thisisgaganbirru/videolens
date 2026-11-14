from ..domain.entities import ApiKey, Principal
from ..domain.ports import AccountDirectory, ApiKeyRepository
from .api_key_access import key_workspace


class ListApiKeysUseCase:
    """The workspace's keys, newest first, revoked ones included (marked)."""

    def __init__(self, *, api_keys: ApiKeyRepository, accounts: AccountDirectory) -> None:
        self._api_keys = api_keys
        self._accounts = accounts

    async def execute(self, principal: Principal) -> list[ApiKey]:
        workspace_id = await key_workspace(principal, self._accounts, owner_only=False)
        return await self._api_keys.list_for_workspace(workspace_id)
