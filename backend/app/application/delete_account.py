"""`DELETE /api/me`: a signed-in person deletes their account for good.

Order matters, and is the whole design:

1. Server-side runs owned by the person (`user:<sub>`) and by each of their
   workspace's API keys (`key:<id>`). Best effort: runs expire within
   `RUN_TTL_SECONDS` anyway, so a Redis hiccup here is logged and does not
   stop the deletion.
2. The identity rows (API keys, memberships, workspaces, the account), in
   one transaction. A failure here is a 500 and nothing else has happened.
3. The identity-provider user, last. A failure here is also a 500; the
   provider user still exists, so the person's session still verifies, and
   retrying finishes the job (step 2 then finds the account `resolve_account`
   re-created on the retry's way in and removes it again).

Retry-safe, not repeatable: an account whose rows are already gone is not an
error here, and step 3 runs regardless, so a retry after a step 3 failure
completes. Once step 3 has succeeded, though, the person's still-valid token
is refused before it gets here: `IdentityProviderUsers` reports the user gone
when `resolve_account` would create rows, so a second `DELETE /api/me` is a
401, and the token cannot re-create the account or mint an API key.
"""

import logging

from ..domain.entities import AuthMethod, Principal
from ..domain.errors import AccountDeletionError, AccountsNotConfiguredError, ForbiddenError
from ..domain.ports import AccountDeleter, AccountDirectory, ApiKeyRepository, RunRepository

logger = logging.getLogger("videolens")

_SUBJECT_PREFIX = "user:"
_FAILED = "We couldn't delete your account just now. Please try again."


class DeleteAccountUseCase:
    def __init__(
        self,
        *,
        accounts: AccountDirectory,
        deleter: AccountDeleter,
        api_keys: ApiKeyRepository,
        runs: RunRepository,
    ) -> None:
        self._accounts = accounts
        self._deleter = deleter
        self._api_keys = api_keys
        self._runs = runs

    async def execute(self, principal: Principal) -> None:
        # Defence in depth behind the route's `require_person`: an API key
        # must never be able to delete the person who owns it.
        if principal.method is not AuthMethod.TOKEN or not principal.subject.startswith(_SUBJECT_PREFIX):
            raise ForbiddenError("Deleting an account needs a signed-in session, not an API key.")
        if not self._accounts.enabled or not self._deleter.enabled:
            raise AccountsNotConfiguredError("Accounts are not available on this server.")
        external_id = principal.subject[len(_SUBJECT_PREFIX):]

        await self._delete_runs(principal)

        try:
            existed = await self._deleter.delete_account(external_id)
        except Exception as exc:  # noqa: BLE001 - mapped to one 500, logged in full
            logger.exception("Account deletion failed deleting rows (account %s)", principal.account_id)
            raise AccountDeletionError(_FAILED, log_detail=f"rows: {type(exc).__name__}") from exc

        try:
            removed_identity = await self._deleter.delete_identity(external_id)
        except Exception as exc:  # noqa: BLE001 - mapped to one 500, logged in full
            logger.exception(
                "Account deletion removed the rows but not the identity-provider user (account %s)",
                principal.account_id,
            )
            raise AccountDeletionError(_FAILED, log_detail=f"identity: {type(exc).__name__}") from exc

        # The account id only: no email, no subject in the log.
        logger.info(
            "Account deleted (account %s, rows %s, identity %s)",
            principal.account_id,
            "removed" if existed else "already gone",
            "removed" if removed_identity else "skipped",
        )

    async def _delete_runs(self, principal: Principal) -> None:
        owners = [principal.owner_id]
        if principal.workspace_id:
            try:
                keys = await self._api_keys.list_for_workspace(principal.workspace_id)
                owners.extend(f"key:{key.key_id}" for key in keys)
            except Exception:  # noqa: BLE001 - runs expire on their own; keep going
                logger.warning(
                    "Account deletion could not list API keys for run cleanup (account %s)",
                    principal.account_id,
                    exc_info=True,
                )
        for owner in owners:
            try:
                await self._runs.delete_for_owner(owner)
            except Exception:  # noqa: BLE001 - runs expire on their own; keep going
                logger.warning(
                    "Account deletion could not remove runs for one owner (account %s)",
                    principal.account_id,
                    exc_info=True,
                )
