"""AccountDeleter adapters: account deletion (`DELETE /api/me`).

Since 2026-11-14 deletion is a 30-day hold (docs/backend/saved-history.md):
`schedule_deletion` only stamps `accounts.deleted_at` / `purge_at`, and
`restore` clears them while the hold lasts. The removal for good
(`delete_account`, `delete_identity`) is the worker's cleanup job, once
`purge_at` has passed.

`SqlAccountDeleter.delete_account` removes every row in one transaction; on
Postgres, the Supabase user through `videolens_private.delete_auth_user`, a
`SECURITY DEFINER` function migration `0002_auth_user_deleter` creates. It
exists because Supabase's `postgres` holds `DELETE` on `auth.users` without
grant option, so the backend's own role cannot be granted it directly, and
the alternative (the service-role key on Railway) is what the auth plan's
decision 2 rules out. On SQLite there is no `auth` schema, so that step is
skipped with a log line.

`InMemoryAccountDeleter` is the counterpart for the in-memory stores a local
`uvicorn` without `DATABASE_URL` gets. It has no identity provider to call:
in that setup a real Supabase user, if any, is left in place (logged).
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, or_, select, text, update

from ...domain.entities import PendingAccountPurge
from ..config import Settings
from .account_directory import InMemoryAccountDirectory
from .account_free_runs import InMemoryAccountFreeRuns
from .api_key_repository import InMemoryApiKeyRepository
from .billing_store import InMemoryBillingAccounts, InMemoryExtraRunLedger
from .database import Database, as_utc
from .saved_run_repository import InMemorySavedRuns
from .schema import (
    account_free_run_holds,
    account_free_runs,
    accounts,
    api_keys,
    billing_accounts,
    billing_extra_runs,
    saved_runs,
    workspace_members,
    workspaces,
)

logger = logging.getLogger("videolens")

_DELETE_AUTH_USER = text("SELECT videolens_private.delete_auth_user(CAST(:user_id AS uuid))")


class SqlAccountDeleter:
    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._db = database

    @property
    def enabled(self) -> bool:
        return self._db.enabled

    async def schedule_deletion(self, external_id: str, *, now: datetime, purge_at: datetime) -> Optional[datetime]:
        async with self._db.connect() as conn:
            # Only an account not already held: a second DELETE keeps the
            # first purge date (no way to push it out by deleting again).
            await conn.execute(
                update(accounts)
                .where(accounts.c.external_id == external_id, accounts.c.purge_at.is_(None))
                .values(deleted_at=now, purge_at=purge_at)
            )
            value = await conn.execute(select(accounts.c.purge_at).where(accounts.c.external_id == external_id))
            row = value.first()
        return as_utc(row.purge_at) if row is not None else None

    async def restore(self, external_id: str, *, now: datetime) -> Optional[bool]:
        async with self._db.connect() as conn:
            row = (
                await conn.execute(select(accounts.c.purge_at).where(accounts.c.external_id == external_id))
            ).first()
            if row is None:
                return None
            if row.purge_at is None:
                return False
            # Conditional on the hold still running, so a restore and the
            # cleanup job can never both win.
            moved = await conn.execute(
                update(accounts)
                .where(accounts.c.external_id == external_id, accounts.c.purge_at > now)
                .values(deleted_at=None, purge_at=None)
            )
        return True if moved.rowcount == 1 else None

    async def due_for_purge(self, now: datetime, *, limit: int) -> list[PendingAccountPurge]:
        async with self._db.connect() as conn:
            rows = (
                await conn.execute(
                    select(accounts.c.id, accounts.c.external_id)
                    .where(accounts.c.purge_at.is_not(None), accounts.c.purge_at <= now)
                    .order_by(accounts.c.purge_at)
                    .limit(limit)
                )
            ).all()
        return [PendingAccountPurge(account_id=row.id, external_id=row.external_id) for row in rows]

    async def delete_account(self, external_id: str, *, due_before: Optional[datetime] = None) -> bool:
        async with self._db.connect() as conn:
            query = select(accounts.c.id).where(accounts.c.external_id == external_id)
            if due_before is not None:
                query = query.where(accounts.c.purge_at.is_not(None), accounts.c.purge_at <= due_before)
            if self._db.dialect == "postgresql":
                # Holds the row against a concurrent restore until commit.
                query = query.with_for_update()
            account_id = await conn.scalar(query)
            if account_id is None:
                return False
            owned = select(workspaces.c.id).where(workspaces.c.owner_account_id == account_id)
            # Children first: the identity foreign keys have no ON DELETE
            # CASCADE. The free-run tables do (0003), but SQLite does not
            # enforce it, so they go explicitly too.
            await conn.execute(delete(account_free_run_holds).where(account_free_run_holds.c.account_id == account_id))
            await conn.execute(delete(account_free_runs).where(account_free_runs.c.account_id == account_id))
            # Billing rows (0004) cascade too. The subscription itself was
            # cancelled in Stripe before this (DeleteAccountUseCase).
            await conn.execute(delete(billing_extra_runs).where(billing_extra_runs.c.account_id == account_id))
            await conn.execute(delete(billing_accounts).where(billing_accounts.c.account_id == account_id))
            # Saved runs (0006) cascade too.
            await conn.execute(delete(saved_runs).where(saved_runs.c.account_id == account_id))
            await conn.execute(delete(api_keys).where(api_keys.c.workspace_id.in_(owned)))
            await conn.execute(
                delete(workspace_members).where(
                    or_(
                        workspace_members.c.workspace_id.in_(owned),
                        workspace_members.c.account_id == account_id,
                    )
                )
            )
            await conn.execute(delete(workspaces).where(workspaces.c.owner_account_id == account_id))
            await conn.execute(delete(accounts).where(accounts.c.id == account_id))
        return True

    async def delete_identity(self, external_id: str) -> bool:
        if self._db.dialect != "postgresql":
            logger.info("Account deletion: no auth schema on %s; identity-provider user not deleted", self._db.dialect)
            return False
        try:
            user_id = str(uuid.UUID(external_id))
        except ValueError:
            # Supabase subjects are UUIDs. Anything else came from another
            # identity provider, which this function cannot reach.
            logger.warning("Account deletion: subject is not a UUID; identity-provider user not deleted")
            return False
        async with self._db.connect() as conn:
            await conn.execute(_DELETE_AUTH_USER, {"user_id": user_id})
        return True


class InMemoryAccountDeleter:
    def __init__(
        self,
        settings: Settings,
        *,
        accounts: InMemoryAccountDirectory,
        api_keys: InMemoryApiKeyRepository,
        free_runs: InMemoryAccountFreeRuns | None = None,
        billing_accounts: InMemoryBillingAccounts | None = None,
        extra_runs: InMemoryExtraRunLedger | None = None,
        saved_runs: InMemorySavedRuns | None = None,
    ) -> None:
        self._saved_runs = saved_runs
        self._billing_accounts = billing_accounts
        self._extra_runs = extra_runs
        self._settings = settings
        self._accounts = accounts
        self._api_keys = api_keys
        self._free_runs = free_runs

    @property
    def enabled(self) -> bool:
        return self._accounts.enabled

    async def schedule_deletion(self, external_id: str, *, now: datetime, purge_at: datetime) -> Optional[datetime]:
        return self._accounts.schedule_deletion(external_id, now, purge_at)

    async def restore(self, external_id: str, *, now: datetime) -> Optional[bool]:
        return self._accounts.restore(external_id, now)

    async def due_for_purge(self, now: datetime, *, limit: int) -> list[PendingAccountPurge]:
        return self._accounts.due_for_purge(now, limit)

    async def delete_account(self, external_id: str, *, due_before: Optional[datetime] = None) -> bool:
        if due_before is not None and not self._accounts.is_due(external_id, due_before):
            return False
        account_id = self._accounts.account_id_for(external_id)
        owned = self._accounts.forget_account(external_id)
        if owned is None:
            return False
        self._api_keys.forget_workspaces(owned)
        if self._free_runs is not None and account_id is not None:
            self._free_runs.forget_account(account_id)
        if account_id is not None:
            for store in (self._billing_accounts, self._extra_runs, self._saved_runs):
                if store is not None:
                    store.forget_account(account_id)
        return True

    async def delete_identity(self, external_id: str) -> bool:
        logger.info("Account deletion: in-memory account store; identity-provider user not deleted")
        return False
