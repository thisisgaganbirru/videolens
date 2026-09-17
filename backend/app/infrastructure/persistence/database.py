"""One async engine per process, shared by every Postgres-backed adapter.

`enabled` is the switch the rest of the system reads: with no
`DATABASE_URL` there is no engine, every adapter reports itself disabled,
and the application behaves exactly as it did before durable storage
existed. Nothing here is touched until the first query, so importing the
module never opens a connection.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from ..config import Settings
from .schema import metadata

logger = logging.getLogger("videolens")


def normalize_database_url(url: str) -> str:
    """Accept the URL forms hosting providers hand out and return one
    SQLAlchemy's async drivers understand.

    Railway and Heroku-style providers emit `postgres://` or `postgresql://`;
    the asyncpg dialect wants `postgresql+asyncpg://`. SQLite is accepted for
    tests and single-machine use with the aiosqlite driver.
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
        self._settings = settings
        self._url = normalize_database_url(settings.database_url)
        self._engine: AsyncEngine | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    @property
    def url(self) -> str:
        return self._url

    @property
    def dialect(self) -> str:
        return self._url.split(":", 1)[0].split("+", 1)[0] if self._url else ""

    def engine(self) -> AsyncEngine:
        if not self.enabled:
            raise RuntimeError("DATABASE_URL is not configured.")
        if self._engine is None:
            kwargs: dict = {"pool_pre_ping": True}
            if self.dialect == "sqlite":
                # SQLite has no pool to speak of and an in-memory database
                # must live on one connection to exist at all.
                from sqlalchemy.pool import StaticPool

                kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
            self._engine = create_async_engine(self._url, **kwargs)
        return self._engine

    def connect(self):
        return self.engine().begin()

    def sessions(self) -> async_sessionmaker:
        return async_sessionmaker(self.engine(), expire_on_commit=False)

    async def create_all(self) -> None:
        """Build the schema straight from metadata - for tests and for a
        first boot with `DB_AUTO_MIGRATE` when Alembic is not present."""
        async with self.engine().begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def migrate(self) -> None:
        """Bring the database to the current Alembic head.

        Runs in a worker thread because Alembic's env.py drives its own event
        loop; a thread without one is the only place that is legal from
        inside a running application.
        """
        if not self.enabled:
            return
        try:
            from alembic import command
            from alembic.config import Config
        except ImportError:
            logger.warning("Alembic is not installed; creating tables from metadata instead")
            await self.create_all()
            return

        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        config = Config(os.path.join(backend_dir, "alembic.ini"))
        config.set_main_option("script_location", os.path.join(backend_dir, "migrations"))
        config.set_main_option("sqlalchemy.url", self._url.replace("%", "%%"))
        await asyncio.to_thread(command.upgrade, config, "head")

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
