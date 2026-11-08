from ..domain.entities import ApiKeyCreated, Principal
from ..domain.ports import AccountDirectory, ApiKeyRepository
from .api_key_access import DEFAULT_SCOPES, key_workspace

MAX_NAME_LENGTH = 80


class CreateApiKeyUseCase:
    """Mints a key for the caller's workspace. Open to every signed-in person
    in this phase (no plan gate); capped at `max_active` live keys."""

    def __init__(self, *, api_keys: ApiKeyRepository, accounts: AccountDirectory, max_active: int) -> None:
        self._api_keys = api_keys
        self._accounts = accounts
        self._max_active = max_active

    async def execute(self, principal: Principal, name: str) -> ApiKeyCreated:
        workspace_id = await key_workspace(principal, self._accounts, owner_only=True)
        label = (name or "").strip()[:MAX_NAME_LENGTH] or "Unnamed key"
        return await self._api_keys.issue(workspace_id, label, list(DEFAULT_SCOPES), max_active=self._max_active)
