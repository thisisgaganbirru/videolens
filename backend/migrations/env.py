"""Alembic environment for the identity schema. Async-aware: the engine is
SQLAlchemy's async one, so the same drivers (asyncpg / aiosqlite) serve the
migrations and the app.

URL precedence: a URL set on the Config by the caller (tests do this), then
`DATABASE_URL` from the environment, then `backend/.env` through `Settings`,
then the placeholder in alembic.ini.
"""

import asyncio
import logging
import uuid
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.infrastructure.config import Settings
from app.infrastructure.persistence.database import normalize_database_url
from app.infrastructure.persistence.schema import metadata

PLACEHOLDER = "videolens-dev.sqlite3"

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

current = config.get_main_option("sqlalchemy.url", "")
if not current or PLACEHOLDER in current:
    configured = normalize_database_url(Settings().database_url)
    if configured:
        config.set_main_option("sqlalchemy.url", configured.replace("%", "%%"))

target_metadata = metadata

server_log = logging.getLogger("alembic.env.server")


def _server_message(_connection, message) -> None:
    """asyncpg drops NOTICE and WARNING messages unless a listener is
    registered; without this, a `RAISE NOTICE` in a migration says nothing."""
    severity = str(getattr(message, "severity", "") or "NOTICE").upper()
    text = getattr(message, "message", str(message))
    level = logging.WARNING if severity in ("WARNING", "ERROR") else logging.INFO
    server_log.log(level, "Postgres %s: %s", severity, text)
    if level >= logging.WARNING:
        config.print_stdout("Postgres %s: %s", severity, text)


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url", "")
    connect_args = {}
    if url.startswith("postgresql+asyncpg"):
        # Same reason as `Database.engine`: the Supavisor transaction pooler
        # does not keep asyncpg's prepared statements between transactions.
        connect_args = {
            "statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__vl_{uuid.uuid4().hex}__",
        }
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
        hide_parameters=True,
    )
    async with connectable.connect() as connection:
        if connectable.dialect.driver == "asyncpg":
            raw = await connection.get_raw_connection()
            raw.driver_connection.add_log_listener(_server_message)
        await connection.run_sync(_run_sync)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
