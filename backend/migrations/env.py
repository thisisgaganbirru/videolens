"""Alembic environment. Async-aware: the engine is SQLAlchemy's async one so
the same driver (asyncpg / aiosqlite) serves migrations and the app."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from app.infrastructure.persistence.database import normalize_database_url
from app.infrastructure.persistence.schema import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `Database.migrate()` sets the URL on the config; the CLI falls back to the
# environment so `alembic upgrade head` works from a shell too.
env_url = normalize_database_url(os.environ.get("DATABASE_URL", ""))
if env_url and not config.get_main_option("sqlalchemy.url", "").startswith(("postgresql", "sqlite+aiosqlite")):
    config.set_main_option("sqlalchemy.url", env_url.replace("%", "%%"))
elif env_url and "videolens-dev.sqlite3" in config.get_main_option("sqlalchemy.url", ""):
    config.set_main_option("sqlalchemy.url", env_url.replace("%", "%%"))

target_metadata = metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_sync)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
