"""One async engine per process, shared by the SQL-backed identity adapters.

`enabled` is the switch: with no `DATABASE_URL` there is no engine and the
container wires the in-memory directory and key store instead. Nothing here
connects until the first query, so importing or constructing it never opens
a socket. The schema belongs to Alembic (`backend/migrations/`), run as a
release step; `create_all` exists for tests only.
"""

import ssl
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote

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
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    elif url.startswith("sqlite://") and "+aiosqlite" not in url:
        return "sqlite+aiosqlite://" + url[len("sqlite://"):]
    if url.startswith("postgresql+asyncpg://"):
        return _sslmode_for_asyncpg(url)
    return url


def _sslmode_for_asyncpg(url: str) -> str:
    """libpq spells the TLS requirement `sslmode=require`; asyncpg's
    `connect()` takes it as `ssl=require` and refuses an unknown `sslmode`
    keyword, which is what SQLAlchemy would pass it from the query string.
    Rename the one parameter, keep its value and every other parameter as
    written. An explicit `ssl=` wins over `sslmode=`."""
    base, sep, query = url.partition("?")
    if not sep or not query:
        return url
    pairs = [pair.split("=", 1) if "=" in pair else [pair, ""] for pair in query.split("&") if pair]
    names = {name for name, _ in pairs}
    if "sslmode" not in names:
        return url
    kept = []
    for name, value in pairs:
        if name == "sslmode":
            if "ssl" in names:
                continue
            name = "ssl"
        kept.append(f"{name}={value}")
    return base + "?" + "&".join(kept)


# What asyncpg's `connect()` takes as a keyword, so what may stay in the
# query string (SQLAlchemy passes every query parameter through as one).
# Anything else (libpq's `options`, `application_name`, `connect_timeout`,
# `sslcert`/`sslkey`...) made every connection fail with a TypeError at the
# first query; it is now refused at startup instead (`database_url_error`).
_ASYNCPG_QUERY_PARAMETERS = frozenset({
    "ssl", "direct_tls", "passfile", "service", "servicefile", "timeout", "command_timeout",
    "statement_cache_size", "max_cached_statement_lifetime", "max_cacheable_statement_size",
    "target_session_attrs", "krbsrvname", "gsslib", "prepared_statement_cache_size",
})
# Translated here into an `ssl.SSLContext`, so it never reaches asyncpg.
_ROOT_CERT_PARAMETER = "sslrootcert"
_VERIFYING_MODES = ("verify-ca", "verify-full")


def _query_pairs(url: str) -> tuple[str, list[tuple[str, str]]]:
    base, _, query = url.partition("?")
    pairs = [tuple(pair.split("=", 1)) if "=" in pair else (pair, "") for pair in query.split("&") if pair]
    return base, pairs


def database_url_error(url: str) -> str | None:
    """Why this (normalized) asyncpg URL cannot be used, or None. Names the
    parameters only, never a value: the URL carries the password."""
    if not url.startswith("postgresql+asyncpg://"):
        return None
    _, pairs = _query_pairs(url)
    names = [name for name, _ in pairs]
    unknown = sorted({name for name in names if name not in _ASYNCPG_QUERY_PARAMETERS | {_ROOT_CERT_PARAMETER}})
    if unknown:
        return (
            "DATABASE_URL carries parameters this app cannot pass to Postgres: "
            + ", ".join(unknown)
            + ". Remove them; sslmode (or ssl) and sslrootcert are supported."
        )
    values = dict(pairs)
    if "ssl" in values and not values["ssl"]:
        return "DATABASE_URL has an sslmode (or ssl) parameter with no value. Give it one, e.g. sslmode=require."
    if _ROOT_CERT_PARAMETER in values:
        if values.get("ssl") not in _VERIFYING_MODES:
            return (
                "DATABASE_URL sets sslrootcert without sslmode=verify-full (or verify-ca). "
                "A root certificate is only used to verify the server; set the mode that does."
            )
        if not values[_ROOT_CERT_PARAMETER]:
            return "DATABASE_URL has an empty sslrootcert. Give the path to the server's CA certificate."
    return None


def split_tls_connect_args(url: str) -> tuple[str, dict]:
    """The URL without `sslrootcert`, and the connect arguments that carry
    it: an `ssl.SSLContext` trusting only that CA, verifying the hostname
    for `verify-full` and not for `verify-ca` (libpq's meaning). Without
    `sslrootcert` the URL is returned unchanged and asyncpg applies `ssl=`
    itself. Raises ValueError for a URL `database_url_error` refuses, or a
    certificate file that cannot be read."""
    error = database_url_error(url)
    if error:
        raise ValueError(error)
    base, pairs = _query_pairs(url)
    values = dict(pairs)
    if _ROOT_CERT_PARAMETER not in values:
        return url, {}
    path = unquote(values[_ROOT_CERT_PARAMETER])
    try:
        context = ssl.create_default_context(cafile=path)
    except (OSError, ssl.SSLError) as exc:
        raise ValueError(
            f"DATABASE_URL's sslrootcert could not be loaded ({type(exc).__name__}). "
            "Check the path and that the file is a PEM CA certificate."
        ) from exc
    if values["ssl"] == "verify-ca":
        context.check_hostname = False  # still CERT_REQUIRED: the chain is verified
    kept = [f"{name}={value}" for name, value in pairs if name not in (_ROOT_CERT_PARAMETER, "ssl")]
    return base + ("?" + "&".join(kept) if kept else ""), {"ssl": context}


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
        # Raises ValueError for a URL that could never connect (unsupported
        # parameters, an unreadable sslrootcert), so the API and the worker
        # refuse to start rather than fail on every query.
        self._url, self._tls_args = split_tls_connect_args(normalize_database_url(settings.database_url))
        self._pool_size = max(1, settings.database_pool_size)
        self._max_overflow = max(0, settings.database_max_overflow)
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
                # Supabase: use the Supavisor *session* pooler (port 5432),
                # not the transaction pooler (6543). asyncpg prepares every
                # statement on its connection and executes it in a later
                # round trip; the transaction pooler may hand those round
                # trips to different server connections, and on dev every
                # signed-in route failed with "prepared statement ... does
                # not exist" even with the cache off and unique names
                # (docs/backend/auth.md, "Pooler"). The cache stays off and
                # the names unique so a pooler that does reuse connections
                # can never collide.
                #
                # On the session pooler each pooled connection holds one real
                # server connection for as long as it is open, so the pool
                # bounds what this process takes from the pooler's session
                # limit: DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW (5 + 10,
                # SQLAlchemy's defaults), per process, API and worker alike.
                self._engine = create_async_engine(
                    self._url,
                    pool_pre_ping=True,
                    pool_size=self._pool_size,
                    max_overflow=self._max_overflow,
                    hide_parameters=True,
                    connect_args={
                        "statement_cache_size": 0,
                        "prepared_statement_name_func": lambda: f"__vl_{uuid.uuid4().hex}__",
                        **self._tls_args,
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
