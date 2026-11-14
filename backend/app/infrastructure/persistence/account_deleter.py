"""AccountDeleter adapters: account deletion (`DELETE /api/me`).

`SqlAccountDeleter` removes the identity rows in one transaction, then, on
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

from sqlalchemy import delete, or_, select, text

from ..config import Settings
from .account_directory import InMemoryAccountDirectory
from .account_free_runs import InMemoryAccountFreeRuns
from .api_key_repository import InMemoryApiKeyRepository
from .billing_store import InMemoryBillingAccounts, InMemoryExtraRunLedger
from .database import Database
from .schema import (
    account_free_run_holds,
    account_free_runs,
    accounts,
    api_keys,
    billing_accounts,
    billing_extra_runs,
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

    async def delete_account(self, external_id: str) -> bool:
        async with self._db.connect() as conn:
            account_id = await conn.scalar(select(accounts.c.id).where(accounts.c.external_id == external_id))
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
    ) -> None:
        self._billing_accounts = billing_accounts
        self._extra_runs = extra_runs
        self._settings = settings
        self._accounts = accounts
        self._api_keys = api_keys
        self._free_runs = free_runs

    @property
    def enabled(self) -> bool:
        return self._accounts.enabled

    async def delete_account(self, external_id: str) -> bool:
        account_id = self._accounts.account_id_for(external_id)
        owned = self._accounts.forget_account(external_id)
        if owned is None:
            return False
        self._api_keys.forget_workspaces(owned)
        if self._free_runs is not None and account_id is not None:
            self._free_runs.forget_account(account_id)
        if account_id is not None:
            for store in (self._billing_accounts, self._extra_runs):
                if store is not None:
                    store.forget_account(account_id)
        return True

    async def delete_identity(self, external_id: str) -> bool:
        logger.info("Account deletion: in-memory account store; identity-provider user not deleted")
        return False
