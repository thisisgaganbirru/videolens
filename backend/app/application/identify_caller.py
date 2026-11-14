"""Maps the credentials on a request to a `Principal`.

The API layer hands over raw header values; this decides what they mean:
which credential wins, which account and workspace it belongs to. The route
never touches the account directory, and the directory never sees a header.
Both `get_principal` and the rate limiter's key read the result of this one
resolver, so they can never disagree about who is calling.

Order, strongest credential first:
1. An API key: `X-Api-Key`, or `Authorization: Bearer vl_live_...`. Routed on
   the prefix alone, so a JWT never costs a key lookup and vice versa.
2. A bearer token from the identity provider (Supabase): a signed-in person.
3. `X-Client-ID`: an anonymous browser, when the deployment allows it.
"""

import asyncio
import logging

from ..domain.entities import AuthMethod, Principal
from ..domain.errors import AuthenticationError, AuthNotConfiguredError, ClientIdInvalidError
from ..domain.policies import SIGNED_IN_ROLE, bearer_credential, is_valid_client_id, looks_like_api_key
from ..domain.ports import AccountDirectory, ApiKeyRepository, TokenVerifier

logger = logging.getLogger("videolens")


def _bearer(authorization: str) -> str:
    """The credential after the `Bearer` scheme, or "". The scheme name is
    case-insensitive (RFC 9110 section 11.1)."""
    return bearer_credential(authorization)


class IdentifyCallerUseCase:
    def __init__(
        self,
        *,
        accounts: AccountDirectory,
        api_keys: ApiKeyRepository,
        verifier: TokenVerifier,
        allow_anonymous: bool,
    ) -> None:
        self._accounts = accounts
        self._api_keys = api_keys
        self._verifier = verifier
        self._allow_anonymous = allow_anonymous

    async def resolve(self, *, authorization: str = "", api_key: str = "", client_id: str = "") -> Principal:
        bearer = _bearer(authorization)
        secret = api_key.strip() or (bearer if looks_like_api_key(bearer) else "")
        if secret:
            return await self.from_api_key(secret)
        if bearer:
            return await self.from_token(bearer)
        if not self._allow_anonymous:
            raise AuthenticationError("Sign in is required.")
        return self.from_client_id(client_id)

    async def from_token(self, token: str) -> Principal:
        try:
            # Off the event loop: a JWKS cache miss is a blocking HTTP fetch.
            claims = await asyncio.to_thread(self._verifier.decode, token)
        except AuthNotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001 - every verification failure is one 401
            # The failure class only; never the token. The verifier logs the kid.
            logger.info("Access token rejected (%s)", type(exc).__name__)
            raise AuthenticationError("Invalid access token.") from exc
        return await self.from_token_claims(claims)

    async def from_token_claims(self, claims: dict) -> Principal:
        subject = str(claims.get("sub", "") or "").strip()
        if not subject:
            raise AuthenticationError("Access token has no subject.")
        # A real, signed-in Supabase user. Supabase anonymous sign-ins carry
        # `is_anonymous: true` (and service tokens another role); either would
        # otherwise get an account, API keys and a rate bucket of its own,
        # one per throwaway sign-in.
        if claims.get("role") != SIGNED_IN_ROLE or claims.get("is_anonymous") is True:
            raise AuthenticationError("Invalid access token.")
        raw_email = claims.get("email")
        email = str(raw_email).strip() or None if raw_email else None
        if not self._accounts.enabled:
            # No account store: a signed-in caller behaves exactly as before
            # accounts existed - a bare subject, the deployment's limits.
            return Principal(subject=f"user:{subject}", authenticated=True, method=AuthMethod.TOKEN, email=email)
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
            email=email or account.email,
        )

    async def from_api_key(self, secret: str) -> Principal:
        key = await self._api_keys.authenticate(secret.strip())
        if key is None:
            logger.info("API key rejected (unknown or revoked)")
            raise AuthenticationError("Invalid API key.")
        workspace = await self._accounts.get_workspace(key.workspace_id)
        if workspace is None:
            logger.info("API key rejected (workspace %s missing)", key.workspace_id)
            raise AuthenticationError("Invalid API key.")
        return Principal(
            subject=f"key:{key.key_id}",
            authenticated=True,
            method=AuthMethod.API_KEY,
            # The account that owns the key's workspace: quota is per person,
            # not per key (`policies.quota_key`).
            account_id=workspace.owner_account_id,
            workspace_id=workspace.workspace_id,
        )

    @staticmethod
    def from_client_id(client_id: str) -> Principal:
        if not is_valid_client_id(client_id):
            raise ClientIdInvalidError("A valid X-Client-ID header is required.")
        return Principal(subject=f"client:{client_id}", authenticated=False)
