"""`POST /api/me/restore`: a person whose account is in the 30-day deletion
hold signs in again and takes it back (docs/backend/saved-history.md).

The only endpoint a held account may use: the route resolves the caller
with `allow_pending_deletion=True`. Everything comes back as it was (API
keys, workspace, saved runs), on the free plan: the subscription was
cancelled at deletion, and resubscribing is a fresh checkout. A held
account's saved runs get a fresh post-cancel window from the restore, so
the hold never eats into it.

Answers:
- restored: the hold was lifted by this call;
- not pending: the account was not in the hold (a repeat, or a stale
  client); nothing changes;
- 410 `restore_window_closed`: the hold already ended; the account is
  removed (or about to be) and cannot come back.
"""

import logging
from datetime import datetime, timezone
from typing import Callable

from ..domain.entities import AuthMethod, Principal
from ..domain.errors import AccountRestoreClosedError, AccountsNotConfiguredError, ForbiddenError
from ..domain.ports import AccountDeleter
from .saved_history import SavedHistory

logger = logging.getLogger("videolens")

_SUBJECT_PREFIX = "user:"

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RestoreAccountUseCase:
    def __init__(
        self, *, deleter: AccountDeleter, history: SavedHistory | None = None, clock: Clock | None = None
    ) -> None:
        self._deleter = deleter
        self._history = history
        self._clock = clock or _utcnow

    async def execute(self, principal: Principal) -> bool:
        """True when this call restored the account, False when it was not
        in the hold."""
        if principal.method is not AuthMethod.TOKEN or not principal.subject.startswith(_SUBJECT_PREFIX):
            raise ForbiddenError("Restoring an account needs a signed-in session, not an API key.")
        if not self._deleter.enabled:
            raise AccountsNotConfiguredError("Accounts are not available on this server.")
        external_id = principal.subject[len(_SUBJECT_PREFIX):]
        outcome = await self._deleter.restore(external_id, now=self._clock())
        if outcome is None:
            raise AccountRestoreClosedError()
        if outcome and principal.account_id and self._history is not None:
            await self._history.rearm_after_restore(principal.account_id)
        if outcome:
            logger.info("Account restored from the deletion hold (account %s)", principal.account_id)
        return outcome
