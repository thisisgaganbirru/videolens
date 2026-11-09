"""IdentityProviderUsers adapters: does Supabase still have this user?

`SqlIdentityProviderUsers` asks Postgres through
`videolens_private.auth_user_exists(uuid)`, a `SECURITY DEFINER` function
from migration `0002_auth_user_deleter` (the backend role cannot read
`auth.users` itself). A subject that is not a UUID cannot be a Supabase user,
so on Postgres it does not exist. On SQLite there is no `auth` schema to ask,
so every subject exists.

`AlwaysPresentIdentityProviderUsers` is the in-memory counterpart: a local
`uvicorn` without `DATABASE_URL` has no identity provider to ask, and its
accounts vanish on restart anyway.
"""

import uuid

from sqlalchemy import text

from ..config import Settings
from .database import Database

_AUTH_USER_EXISTS = text("SELECT videolens_private.auth_user_exists(CAST(:user_id AS uuid))")


class SqlIdentityProviderUsers:
    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._db = database

    async def exists(self, external_id: str) -> bool:
        if self._db.dialect != "postgresql":
            return True
        try:
            user_id = str(uuid.UUID(external_id))
        except ValueError:
            return False
        async with self._db.connect() as conn:
            return bool(await conn.scalar(_AUTH_USER_EXISTS, {"user_id": user_id}))


class AlwaysPresentIdentityProviderUsers:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def exists(self, external_id: str) -> bool:
        return True
