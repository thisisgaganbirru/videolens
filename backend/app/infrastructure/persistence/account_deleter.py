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
from .api_key_repository import InMemoryApiKeyRepository
from .database import Database
from .schema import accounts, api_keys, workspace_members, workspaces

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
            # Children first: the foreign keys have no ON DELETE CASCADE.
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
    ) -> None:
        self._settings = settings
        self._accounts = accounts
        self._api_keys = api_keys

    @property
    def enabled(self) -> bool:
        return self._accounts.enabled

    async def delete_account(self, external_id: str) -> bool:
        owned = self._accounts.forget_account(external_id)
        if owned is None:
            return False
        self._api_keys.forget_workspaces(owned)
        return True

    async def delete_identity(self, external_id: str) -> bool:
        logger.info("Account deletion: in-memory account store; identity-provider user not deleted")
        return False
