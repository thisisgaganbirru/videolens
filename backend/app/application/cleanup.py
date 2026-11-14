"""The worker's hourly cleanup (docs/backend/saved-history.md):

1. Accounts whose 30-day deletion hold has ended are removed for good: the
   Supabase user first (so nobody can sign in to a half-removed account),
   then every row, saved runs included. A failure leaves the account row,
   so the next tick retries; both steps are idempotent. An account that
   somehow still holds a live subscription has it cancelled first, and is
   skipped (logged) if that fails: never remove an account that still pays.
2. Saved runs whose post-cancel window has passed are removed, after the
   window is started for any account whose paid plan ended without a
   webhook saying so.

Bounded per tick (`limit`s), idempotent, safe to run on any number of
workers at once (each removal is a conditional write), and a no-op without
an account store. Step 2 is also a no-op with billing off.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from ..domain.errors import SubscriptionCancelFailedError
from ..domain.ports import AccountDeleter
from .billing import BillingPlans
from .delete_account import cancel_account_subscription
from .saved_history import SavedHistory

logger = logging.getLogger("videolens")

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CleanupReport:
    accounts_removed: int = 0
    accounts_skipped: int = 0
    windows_started: int = 0
    saved_runs_removed: int = 0


class AccountCleanupUseCase:
    def __init__(
        self,
        *,
        deleter: AccountDeleter,
        history: SavedHistory | None = None,
        billing: BillingPlans | None = None,
        accounts_per_tick: int = 25,
        clock: Clock | None = None,
    ) -> None:
        self._deleter = deleter
        self._history = history
        self._billing = billing
        self._limit = max(1, accounts_per_tick)
        self._clock = clock or _utcnow

    async def run(self) -> CleanupReport:
        removed, skipped = await self._purge_held_accounts()
        started = runs_removed = 0
        if self._history is not None:
            try:
                started = await self._history.arm_lapsed(limit=self._limit * 8)
                runs_removed = await self._history.purge_expired(limit=self._limit)
            except Exception:  # noqa: BLE001 - the next tick tries again
                logger.exception("Saved-history cleanup failed; it will be retried")
        return CleanupReport(
            accounts_removed=removed,
            accounts_skipped=skipped,
            windows_started=started,
            saved_runs_removed=runs_removed,
        )

    async def _purge_held_accounts(self) -> tuple[int, int]:
        if not self._deleter.enabled:
            return 0, 0
        now = self._clock()
        try:
            due = await self._deleter.due_for_purge(now, limit=self._limit)
        except Exception:  # noqa: BLE001
            logger.exception("Could not read the accounts whose deletion hold ended")
            return 0, 0
        removed = skipped = 0
        for pending in due:
            try:
                await cancel_account_subscription(self._billing, pending.account_id, only_if_live=True)
            except SubscriptionCancelFailedError:
                logger.error("Account %s not removed: its subscription could not be cancelled", pending.account_id)
                skipped += 1
                continue
            try:
                identity = await self._deleter.delete_identity(pending.external_id)
                gone = await self._deleter.delete_account(pending.external_id, due_before=now)
            except Exception:  # noqa: BLE001 - left in place; the next tick retries
                logger.exception("Could not remove account %s after its deletion hold", pending.account_id)
                skipped += 1
                continue
            if gone:
                removed += 1
                logger.info(
                    "Account %s removed for good after its deletion hold (identity %s)",
                    pending.account_id,
                    "removed" if identity else "skipped",
                )
        return removed, skipped
