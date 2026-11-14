"""`DELETE /api/me`: a signed-in person deletes their account.

Since 2026-11-14 (owner decision, docs/backend/saved-history.md) this puts
the account in a 30-day hold instead of removing it. To the person it is
deleted: every endpoint refuses it (410 `account_pending_deletion`) and its
API keys stop working. The rows, the saved runs and the Supabase user stay,
hidden, so signing in again within the hold can restore it
(`RestoreAccountUseCase`). After the hold the worker's cleanup job removes
everything for good (`PurgeDeletedAccountsUseCase`).

Order:

0. The account's Stripe subscription, cancelled now (docs/backend/billing.md):
   no proration credit, and usage not yet invoiced (completed extra runs)
   invoiced immediately. The person comes back on the free plan if they
   restore. If Stripe cannot be reached the deletion is refused (503
   `subscription_cancel_failed`) with nothing changed, rather than leave a
   paying account nobody can sign in to manage.
1. Server-side runs owned by the person (`user:<sub>`) and by each of their
   workspace's API keys (`key:<id>`). Best effort: they expire within
   `RUN_TTL_SECONDS` anyway.
2. The hold itself: `accounts.deleted_at` / `purge_at`, one write. A failure
   here is a 500 and the account still works (retry).

The Supabase user is deliberately NOT deleted here any more: without it the
person could never sign in to restore. The cleanup job deletes it (through
the same `SECURITY DEFINER` function, `0002_auth_user_deleter`) when the
hold ends.

A second `DELETE /api/me` never reaches this: the held account is refused
(410) on the way in, so the first purge date stands.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..domain.entities import AuthMethod, Principal
from ..domain.errors import (
    AccountDeletionError,
    AccountsNotConfiguredError,
    ForbiddenError,
    SubscriptionCancelFailedError,
)
from ..domain.policies import subscription_is_live
from ..domain.ports import AccountDeleter, AccountDirectory, ApiKeyRepository, RunRepository
from .billing import BillingPlans, ExtraRunBilling

logger = logging.getLogger("videolens")

_SUBJECT_PREFIX = "user:"
_FAILED = "We couldn't delete your account just now. Please try again."

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def cancel_account_subscription(
    billing: BillingPlans | None, account_id: str | None, *, only_if_live: bool = False
) -> None:
    """Cancel the account's Stripe subscription now, if it holds one. Raises
    `SubscriptionCancelFailedError` when it cannot tell or cannot cancel,
    so the caller stops before changing anything. Shared by deletion and the
    cleanup job's last check before removing an account for good."""
    if billing is None or account_id is None or not billing.accounts.enabled:
        return
    try:
        account = await billing.accounts.get(account_id)
    except Exception as exc:  # noqa: BLE001 - cannot tell whether it pays: stop
        logger.exception("Could not read the billing account (account %s)", account_id)
        raise SubscriptionCancelFailedError(log_detail=f"billing read: {type(exc).__name__}") from exc
    if account is None or not account.stripe_subscription_id:
        return
    if only_if_live and not subscription_is_live(account.status):
        return
    if not billing.gateway.enabled:
        if subscription_is_live(account.status):
            # Billing was switched off with a live subscription on file.
            logger.error("Refused: live subscription but billing is off (account %s)", account_id)
            raise SubscriptionCancelFailedError(log_detail="live subscription on file, STRIPE_* not configured")
        return
    # Completed extra runs first, so the final invoice carries them.
    await ExtraRunBilling(plans=billing).flush_due()
    try:
        # Whatever the row says: a missed webhook must not leave one running.
        await billing.gateway.cancel_subscription(account.stripe_subscription_id)
    except Exception as exc:  # noqa: BLE001 - refused, logged in full
        logger.exception("Could not cancel the subscription (account %s)", account_id)
        raise SubscriptionCancelFailedError(log_detail=f"stripe cancel: {type(exc).__name__}") from exc
    logger.info("Cancelled subscription %s (account %s)", account.stripe_subscription_id, account_id)


class DeleteAccountUseCase:
    def __init__(
        self,
        *,
        accounts: AccountDirectory,
        deleter: AccountDeleter,
        api_keys: ApiKeyRepository,
        runs: RunRepository,
        billing: BillingPlans | None = None,
        hold_days: int = 30,
        clock: Clock | None = None,
    ) -> None:
        self._billing = billing
        self._accounts = accounts
        self._deleter = deleter
        self._api_keys = api_keys
        self._runs = runs
        self._hold = timedelta(days=max(0, hold_days))
        self._clock = clock or _utcnow

    async def execute(self, principal: Principal) -> datetime:
        """Put the account in the hold. Returns when it will be removed for
        good (the restore deadline)."""
        # Defence in depth behind the route's `require_person`: an API key
        # must never be able to delete the person who owns it.
        if principal.method is not AuthMethod.TOKEN or not principal.subject.startswith(_SUBJECT_PREFIX):
            raise ForbiddenError("Deleting an account needs a signed-in session, not an API key.")
        if not self._accounts.enabled or not self._deleter.enabled:
            raise AccountsNotConfiguredError("Accounts are not available on this server.")
        external_id = principal.subject[len(_SUBJECT_PREFIX):]

        await cancel_account_subscription(self._billing, principal.account_id)
        await self._delete_runs(principal)

        now = self._clock()
        try:
            purge_at = await self._deleter.schedule_deletion(external_id, now=now, purge_at=now + self._hold)
        except Exception as exc:  # noqa: BLE001 - mapped to one 500, logged in full
            logger.exception("Account deletion failed scheduling the hold (account %s)", principal.account_id)
            raise AccountDeletionError(_FAILED, log_detail=f"hold: {type(exc).__name__}") from exc

        # The account id only: no email, no subject in the log.
        logger.info(
            "Account deletion scheduled (account %s, removed for good after %s)",
            principal.account_id,
            purge_at.isoformat() if purge_at else "n/a",
        )
        return purge_at or now + self._hold

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
