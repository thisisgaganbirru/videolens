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

An account in the 30-day deletion hold (docs/backend/saved-history.md) is
refused here, once, for every endpoint: a session gets
`AccountPendingDeletionError` (410, so the client can offer the restore),
an API key of that account is simply invalid (401). Only the restore route
asks with `allow_pending_deletion=True`.
"""

import asyncio
import logging

from ..domain.entities import AuthMethod, Principal
from ..domain.errors import (
    AccountPendingDeletionError,
    AuthenticationError,
    AuthNotConfiguredError,
    ClientIdInvalidError,
    RateLimitedError,
)
from ..domain.policies import (
    SIGNED_IN_ROLE,
    bearer_credential,
    is_valid_client_id,
    is_well_formed_api_key,
    looks_like_api_key,
)
from ..domain.ports import AccountDirectory, ApiKeyRepository, CredentialFailureGuard, TokenVerifier

logger = logging.getLogger("videolens")

TOO_MANY_FAILED_CREDENTIALS_MESSAGE = (
    "Too many sign-in attempts that didn't work from this network. Wait a few minutes and try again."
)


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
        failures: CredentialFailureGuard | None = None,
    ) -> None:
        self._accounts = accounts
        self._api_keys = api_keys
        self._verifier = verifier
        self._allow_anonymous = allow_anonymous
        # None (tests, older wiring) = failed credentials are not limited.
        self._failures = failures

    async def resolve(
        self,
        *,
        authorization: str = "",
        api_key: str = "",
        client_id: str = "",
        allow_pending_deletion: bool = False,
        client_ip: str = "",
    ) -> Principal:
        bearer = _bearer(authorization)
        secret = api_key.strip() or (bearer if looks_like_api_key(bearer) else "")
        if secret or bearer:
            # Before the key lookup or the token check: an IP that has sent
            # too many credentials that failed costs nothing more.
            await self._refuse_if_blocked(client_ip)
            try:
                if secret:
                    return await self.from_api_key(secret)
                return await self.from_token(bearer, allow_pending_deletion=allow_pending_deletion)
            except AuthenticationError:
                await self._record_failure(client_ip)
                raise
        if not self._allow_anonymous:
            raise AuthenticationError("Sign in is required.")
        return self.from_client_id(client_id)

    async def _refuse_if_blocked(self, client_ip: str) -> None:
        if self._failures is None:
            return
        try:
            retry_after = await self._failures.retry_after(client_ip)
        except Exception:  # noqa: BLE001 - a counter outage must not lock everyone out
            logger.warning("Could not read the failed-credential counter", exc_info=True)
            return
        if retry_after is not None:
            raise RateLimitedError(TOO_MANY_FAILED_CREDENTIALS_MESSAGE, retry_after_seconds=retry_after)

    async def _record_failure(self, client_ip: str) -> None:
        if self._failures is None:
            return
        try:
            await self._failures.record_failure(client_ip)
        except Exception:  # noqa: BLE001 - never replace the 401 with a 500
            logger.warning("Could not count a failed credential", exc_info=True)

    async def from_token(self, token: str, *, allow_pending_deletion: bool = False) -> Principal:
        try:
            # Off the event loop: a JWKS cache miss is a blocking HTTP fetch.
            claims = await asyncio.to_thread(self._verifier.decode, token)
        except AuthNotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001 - every verification failure is one 401
            # The failure class only; never the token. The verifier logs the kid.
            logger.info("Access token rejected (%s)", type(exc).__name__)
            raise AuthenticationError("Invalid access token.") from exc
        return await self.from_token_claims(claims, allow_pending_deletion=allow_pending_deletion)

    async def from_token_claims(self, claims: dict, *, allow_pending_deletion: bool = False) -> Principal:
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
        if account.pending_deletion and not allow_pending_deletion:
            raise AccountPendingDeletionError(account.purge_at)
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
        secret = secret.strip()
        if not is_well_formed_api_key(secret):
            # Not the shape of any key we issue: no database read for it.
            logger.info("API key rejected (malformed)")
            raise AuthenticationError("Invalid API key.")
        key = await self._api_keys.authenticate(secret)
        if key is None:
            logger.info("API key rejected (unknown or revoked)")
            raise AuthenticationError("Invalid API key.")
        workspace = await self._accounts.get_workspace(key.workspace_id)
        if workspace is None:
            logger.info("API key rejected (workspace %s missing)", key.workspace_id)
            raise AuthenticationError("Invalid API key.")
        owner = await self._accounts.get_account(workspace.owner_account_id)
        if owner is not None and owner.pending_deletion:
            # A deleted account's keys stop working at once; they come back
            # with the account if it is restored.
            logger.info("API key rejected (account %s pending deletion)", workspace.owner_account_id)
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
