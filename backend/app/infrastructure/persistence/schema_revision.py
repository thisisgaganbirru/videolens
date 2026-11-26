"""Reads `alembic_version` through the shared engine (the
`SchemaRevisionReader` port). Comparing it with what the code expects is
the domain's job (`domain/schema_revision.py`).

Asks the catalog first, so a missing table or a missing privilege is a
reading, not an exception to classify: on Postgres `to_regclass` and
`has_table_privilege`, on SQLite `sqlite_master`. The query is the startup
database ping as well; it never raises.
"""

import logging

from sqlalchemy import text

from ...domain.schema_revision import SchemaReading
from .database import Database

logger = logging.getLogger("videolens")


class SqlSchemaRevisionReader:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def read(self) -> SchemaReading:
        try:
            async with self._database.engine().connect() as conn:
                if self._database.dialect == "sqlite":
                    present = (
                        await conn.execute(
                            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'")
                        )
                    ).first() is not None
                    if not present:
                        return SchemaReading(table_present=False)
                else:
                    present = (await conn.execute(text("SELECT to_regclass('alembic_version') IS NOT NULL"))).scalar()
                    if not present:
                        return SchemaReading(table_present=False)
                    allowed = (
                        await conn.execute(text("SELECT has_table_privilege('alembic_version', 'SELECT')"))
                    ).scalar()
                    if not allowed:
                        return SchemaReading(readable=False)
                rows = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
        except Exception as exc:  # noqa: BLE001 - reported as a reading; the class name only
            logger.error("Could not read the database schema revision: %s", type(exc).__name__)
            return SchemaReading(reachable=False)
        return SchemaReading(revisions=tuple(str(r) for r in rows), readable=bool(rows))
