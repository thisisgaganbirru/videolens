"""One async engine per process, shared by the SQL-backed identity adapters.

`enabled` is the switch: with no `DATABASE_URL` there is no engine and the
container wires the in-memory directory and key store instead. Nothing here
connects until the first query, so importing or constructing it never opens
a socket. The schema belongs to Alembic (`backend/migrations/`), run as a
release step; `create_all` exists for tests only.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ..config import Settings
from .schema import metadata


def normalize_database_url(url: str) -> str:
    """Accept the URL forms hosting providers hand out and return one
    SQLAlchemy's async drivers understand.

    Supabase, Railway and Heroku-style providers emit `postgres://` or
    `postgresql://`; the asyncpg dialect wants `postgresql+asyncpg://`. SQLite
    is accepted for tests and single-machine use with the aiosqlite driver.
    """
    url = url.strip()
    if not url:
        return ""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        return "sqlite+aiosqlite://" + url[len("sqlite://"):]
    return url


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything downstream compares
    against aware ones. Postgres returns them aware already."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class Database:
    def __init__(self, settings: Settings) -> None:
        self._url = normalize_database_url(settings.database_url)
        self._engine: AsyncEngine | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    @property
    def dialect(self) -> str:
        return self._url.split(":", 1)[0].split("+", 1)[0] if self._url else ""

    def engine(self) -> AsyncEngine:
        if not self.enabled:
            raise RuntimeError("DATABASE_URL is not configured.")
        if self._engine is None:
            # `hide_parameters`: a database error's text would otherwise carry
            # the bound values (an email, a Supabase user id) into the logs.
            if self.dialect == "sqlite":
                # An in-memory SQLite database exists only on its one
                # connection, so there must be exactly one.
                from sqlalchemy.pool import StaticPool

                self._engine = create_async_engine(
                    self._url,
                    poolclass=StaticPool,
                    connect_args={"check_same_thread": False},
                    hide_parameters=True,
                )
            else:
                # Supabase's Supavisor transaction pooler (port 6543) hands
                # each transaction to whichever server connection is free, so
                # asyncpg's per-connection prepared-statement cache would name
                # statements that do not exist on the next one. Disable the
                # cache and give every statement a unique name.
                self._engine = create_async_engine(
                    self._url,
                    pool_pre_ping=True,
                    hide_parameters=True,
                    connect_args={
                        "statement_cache_size": 0,
                        "prepared_statement_name_func": lambda: f"__vl_{uuid.uuid4().hex}__",
                    },
                )
        return self._engine

    def connect(self):
        """A transaction: `async with database.connect() as conn:` commits on
        exit and rolls back on an exception."""
        return self.engine().begin()

    async def create_all(self) -> None:
        """Build the schema straight from metadata. Tests only: a deployed
        database is migrated with Alembic."""
        async with self.engine().begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def ping(self) -> bool:
        if not self.enabled:
            return False
        from sqlalchemy import text

        async with self.engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
