"""Maps a verified credential to a `Principal`.

The interface layer verifies the credential (a JWT signature, an API key's
presence in a header); this decides what it means - which account, which
workspace, which plan - so that the route never touches the account
directory and the directory never sees an HTTP header.
"""

from ..domain.entities import AuthMethod, Principal
from ..domain.entitlements import Plan
from ..domain.errors import AuthenticationError
from ..domain.policies import is_valid_client_id
from ..domain.ports import AccountDirectory, ApiKeyRepository


class IdentifyCallerUseCase:
    def __init__(self, *, accounts: AccountDirectory, api_keys: ApiKeyRepository) -> None:
        self._accounts = accounts
        self._api_keys = api_keys

    async def from_token_claims(self, claims: dict) -> Principal:
        subject = str(claims.get("sub", "")).strip()
        if not subject:
            raise AuthenticationError("Access token has no subject.")
        email = claims.get("email")
        email = str(email).strip() or None if email else None
        if not self._accounts.enabled:
            # No database: a signed-in caller behaves exactly as before plans
            # existed - their own history, the deployment-wide limits.
            return Principal(
                subject=f"user:{subject}",
                authenticated=True,
                method=AuthMethod.TOKEN,
                email=email,
            )
        account = await self._accounts.resolve_account(subject, email)
        workspace = (
            await self._accounts.get_workspace(account.default_workspace_id)
            if account.default_workspace_id
            else None
        )
        return Principal(
            subject=f"user:{subject}",
            authenticated=True,
            method=AuthMethod.TOKEN,
            account_id=account.account_id,
            workspace_id=workspace.workspace_id if workspace else None,
            plan=workspace.plan if workspace else Plan.FREE,
            email=email or account.email,
        )

    async def from_api_key(self, secret: str) -> Principal:
        key = await self._api_keys.authenticate(secret.strip())
        if key is None:
            raise AuthenticationError("Invalid API key.")
        workspace = await self._accounts.get_workspace(key.workspace_id)
        if workspace is None:
            raise AuthenticationError("Invalid API key.")
        return Principal(
            subject=f"key:{key.key_id}",
            authenticated=True,
            method=AuthMethod.API_KEY,
            workspace_id=workspace.workspace_id,
            plan=workspace.plan,
        )

    @staticmethod
    def from_client_id(client_id: str) -> Principal:
        if not is_valid_client_id(client_id):
            raise AuthenticationError("A valid X-Client-ID header is required.")
        return Principal(subject=f"client:{client_id}", authenticated=False)
