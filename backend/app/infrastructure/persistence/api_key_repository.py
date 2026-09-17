"""ApiKeyRepository adapter: keys are stored as a SHA-256 digest of the
secret, so a database read never yields a usable credential. The secret's
format is `vl_live_<prefix>_<random>`; the prefix is stored in clear so a
listing can show which key is which."""

import hashlib
import secrets
import uuid
from typing import Optional

from sqlalchemy import insert, select, update

from ...domain.entities import ApiKey, IssuedApiKey
from .database import Database, as_utc, utcnow
from .schema import api_keys

KEY_PREFIX = "vl_live_"


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def looks_like_api_key(value: str) -> bool:
    return value.startswith(KEY_PREFIX)


class PostgresApiKeyRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    @staticmethod
    def _key(row) -> ApiKey:
        return ApiKey(
            key_id=row.id,
            workspace_id=row.workspace_id,
            name=row.name,
            prefix=row.prefix,
            scopes=list(row.scopes or []),
            last_used_at=as_utc(row.last_used_at),
            revoked_at=as_utc(row.revoked_at),
            created_at=as_utc(row.created_at),
        )

    async def issue(self, workspace_id: str, name: str, scopes: list[str]) -> IssuedApiKey:
        short = secrets.token_hex(4)
        secret = f"{KEY_PREFIX}{short}_{secrets.token_urlsafe(32)}"
        prefix = f"{KEY_PREFIX}{short}"
        now = utcnow()
        key_id = str(uuid.uuid4())
        async with self._db.connect() as conn:
            await conn.execute(
                insert(api_keys).values(
                    id=key_id,
                    workspace_id=workspace_id,
                    name=name,
                    prefix=prefix,
                    key_hash=hash_secret(secret),
                    scopes=scopes,
                    active=True,
                    created_at=now,
                )
            )
        key = ApiKey(
            key_id=key_id,
            workspace_id=workspace_id,
            name=name,
            prefix=prefix,
            scopes=scopes,
            created_at=now,
        )
        return IssuedApiKey(key=key, secret=secret)

    async def authenticate(self, secret: str) -> Optional[ApiKey]:
        if not self._db.enabled or not looks_like_api_key(secret):
            return None
        digest = hash_secret(secret)
        async with self._db.connect() as conn:
            row = (
                await conn.execute(
                    select(api_keys).where(api_keys.c.key_hash == digest, api_keys.c.active.is_(True))
                )
            ).first()
            if row is None:
                return None
            await conn.execute(update(api_keys).where(api_keys.c.id == row.id).values(last_used_at=utcnow()))
        return self._key(row)

    async def list_for_workspace(self, workspace_id: str) -> list[ApiKey]:
        if not self._db.enabled:
            return []
        async with self._db.connect() as conn:
            rows = (
                await conn.execute(
                    select(api_keys)
                    .where(api_keys.c.workspace_id == workspace_id)
                    .order_by(api_keys.c.created_at.desc())
                )
            ).all()
        return [self._key(row) for row in rows]

    async def revoke(self, workspace_id: str, key_id: str) -> bool:
        if not self._db.enabled:
            return False
        async with self._db.connect() as conn:
            result = await conn.execute(
                update(api_keys)
                .where(
                    api_keys.c.id == key_id,
                    api_keys.c.workspace_id == workspace_id,
                    api_keys.c.active.is_(True),
                )
                .values(active=False, revoked_at=utcnow())
            )
        return bool(result.rowcount)

    async def close(self) -> None:
        await self._db.close()
