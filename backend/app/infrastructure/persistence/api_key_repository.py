"""ApiKeyRepository adapters.

A key is `vl_live_` + 32 random bytes, base64url (43 characters). Only its
SHA-256 is stored, so a database read never yields a usable credential; the
plaintext is returned once, at issue. SHA-256 rather than a slow hash on
purpose: 256 bits of randomness make brute force irrelevant, and a slow hash
would only add latency to every agent call. `prefix` (`vl_live_` plus the
first eight random characters) is kept in clear so a listing is
recognisable; it is far too little to authenticate with.

`last_used_at` is written at most once a minute per key: an agent polling a
run every few seconds must not turn every read into a database write.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, insert, select, update

from ...domain.entities import ApiKey, ApiKeyCreated
from ...domain.errors import ApiKeyLimitError
from ...domain.policies import API_KEY_PREFIX, looks_like_api_key
from .database import Database, as_utc, utcnow
from .schema import api_keys, workspaces

_SECRET_BYTES = 32
_DISPLAY_CHARS = 8
LAST_USED_RESOLUTION = timedelta(minutes=1)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_secret() -> tuple[str, str]:
    """(secret, display prefix)."""
    random_part = secrets.token_urlsafe(_SECRET_BYTES)
    return f"{API_KEY_PREFIX}{random_part}", f"{API_KEY_PREFIX}{random_part[:_DISPLAY_CHARS]}"


def _limit_message(max_active: int) -> str:
    return f"You can have at most {max_active} active API keys. Revoke one to create another."


def _due_for_touch(last_used_at: datetime | None, now: datetime) -> bool:
    return last_used_at is None or now - last_used_at >= LAST_USED_RESOLUTION


class SqlApiKeyRepository:
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

    async def issue(self, workspace_id: str, name: str, scopes: list[str], *, max_active: int) -> ApiKeyCreated:
        secret, prefix = generate_secret()
        now = utcnow()
        key_id = str(uuid.uuid4())
        async with self._db.connect() as conn:
            # Lock the workspace row (Postgres; a no-op on SQLite) so two
            # concurrent creations cannot both slip under the cap.
            await conn.execute(select(workspaces.c.id).where(workspaces.c.id == workspace_id).with_for_update())
            active = await conn.scalar(
                select(func.count())
                .select_from(api_keys)
                .where(api_keys.c.workspace_id == workspace_id, api_keys.c.active.is_(True))
            )
            if (active or 0) >= max_active:
                raise ApiKeyLimitError(_limit_message(max_active))
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
        key = ApiKey(key_id=key_id, workspace_id=workspace_id, name=name, prefix=prefix, scopes=scopes, created_at=now)
        return ApiKeyCreated(key=key, secret=secret)

    async def authenticate(self, secret: str) -> Optional[ApiKey]:
        if not self._db.enabled or not looks_like_api_key(secret):
            return None
        async with self._db.connect() as conn:
            row = (
                await conn.execute(
                    select(api_keys).where(api_keys.c.key_hash == hash_secret(secret), api_keys.c.active.is_(True))
                )
            ).first()
            if row is None:
                return None
            key = self._key(row)
            now = utcnow()
            if _due_for_touch(key.last_used_at, now):
                await conn.execute(update(api_keys).where(api_keys.c.id == key.key_id).values(last_used_at=now))
                key.last_used_at = now
        return key

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
                .where(api_keys.c.id == key_id, api_keys.c.workspace_id == workspace_id, api_keys.c.active.is_(True))
                .values(active=False, revoked_at=utcnow())
            )
        return bool(result.rowcount)

    async def close(self) -> None:
        await self._db.close()


class InMemoryApiKeyRepository:
    """Process-local keys for a deployment with no `DATABASE_URL`. Same rules
    as the SQL adapter (hash only, cap, throttled `last_used_at`); gone on
    restart. With `enabled=False` it knows no keys and issues none."""

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._keys: dict[str, ApiKey] = {}  # by key_id
        self._by_hash: dict[str, str] = {}

    async def issue(self, workspace_id: str, name: str, scopes: list[str], *, max_active: int) -> ApiKeyCreated:
        if not self._enabled:
            raise RuntimeError("API keys are not available without an account store.")
        active = sum(1 for key in self._keys.values() if key.workspace_id == workspace_id and key.active)
        if active >= max_active:
            raise ApiKeyLimitError(_limit_message(max_active))
        secret, prefix = generate_secret()
        key = ApiKey(
            key_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            name=name,
            prefix=prefix,
            scopes=list(scopes),
            created_at=utcnow(),
        )
        self._keys[key.key_id] = key
        self._by_hash[hash_secret(secret)] = key.key_id
        return ApiKeyCreated(key=key.model_copy(), secret=secret)

    async def authenticate(self, secret: str) -> Optional[ApiKey]:
        if not self._enabled or not looks_like_api_key(secret):
            return None
        key_id = self._by_hash.get(hash_secret(secret))
        key = self._keys.get(key_id) if key_id else None
        if key is None or not key.active:
            return None
        now = utcnow()
        if _due_for_touch(key.last_used_at, now):
            key.last_used_at = now
        return key.model_copy()

    async def list_for_workspace(self, workspace_id: str) -> list[ApiKey]:
        keys = [key.model_copy() for key in self._keys.values() if key.workspace_id == workspace_id]
        return sorted(keys, key=lambda key: key.created_at, reverse=True)

    async def revoke(self, workspace_id: str, key_id: str) -> bool:
        key = self._keys.get(key_id)
        if key is None or key.workspace_id != workspace_id or not key.active:
            return False
        key.revoked_at = utcnow()
        return True

    async def close(self) -> None:
        return None
