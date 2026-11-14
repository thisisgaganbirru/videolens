from ..domain.entities import ApiKeyCreated, Principal
from ..domain.errors import AuthenticationError
from ..domain.ports import AccountDirectory, ApiKeyRepository, IdentityProviderUsers
from .api_key_access import DEFAULT_SCOPES, key_workspace

MAX_NAME_LENGTH = 80
_SUBJECT_PREFIX = "user:"


class CreateApiKeyUseCase:
    """Mints a key for the caller's workspace. Open to every signed-in person
    in this phase (no plan gate); capped at `max_active` live keys.

    `users` (when given) is asked right before the key is issued: an account
    deletion that removed the rows while this request was in flight, or a
    token that outlived its user, must not leave a key behind that nobody
    can sign in to revoke."""

    def __init__(
        self,
        *,
        api_keys: ApiKeyRepository,
        accounts: AccountDirectory,
        max_active: int,
        users: IdentityProviderUsers | None = None,
    ) -> None:
        self._api_keys = api_keys
        self._accounts = accounts
        self._max_active = max_active
        self._users = users

    async def execute(self, principal: Principal, name: str) -> ApiKeyCreated:
        workspace_id = await key_workspace(principal, self._accounts, owner_only=True)
        if self._users is not None and principal.subject.startswith(_SUBJECT_PREFIX):
            if not await self._users.exists(principal.subject[len(_SUBJECT_PREFIX):]):
                raise AuthenticationError("Invalid access token.")
        label = (name or "").strip()[:MAX_NAME_LENGTH] or "Unnamed key"
        return await self._api_keys.issue(workspace_id, label, list(DEFAULT_SCOPES), max_active=self._max_active)
