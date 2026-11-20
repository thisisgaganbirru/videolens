import asyncio
import os
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.domain.schema_revision import EXPECTED_SCHEMA_REVISION, SchemaReading
from app.infrastructure.config import Settings
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.schema_revision import SqlSchemaRevisionReader

BACKEND = Path(__file__).resolve().parents[3]


def _upgrade(path: str, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
    config.attributes["configure_logger"] = False
    with mock.patch.dict(os.environ, {"DATABASE_URL": ""}):
        command.upgrade(config, revision)


class SqliteReaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name, "schema.sqlite3").as_posix()
        self.database = Database(Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{self.path}"))
        self.addAsyncCleanup(self.database.close)

    async def test_migrated_database_reads_its_revision(self) -> None:
        # env.py calls asyncio.run, so off this test's loop.
        await asyncio.to_thread(_upgrade, self.path, "head")
        reading = await SqlSchemaRevisionReader(self.database).read()
        self.assertEqual(reading, SchemaReading(revisions=(EXPECTED_SCHEMA_REVISION,)))

    async def test_older_database_reads_the_older_revision(self) -> None:
        # env.py calls asyncio.run, so off this test's loop.
        await asyncio.to_thread(_upgrade, self.path, "0006_saved_history")
        reading = await SqlSchemaRevisionReader(self.database).read()
        self.assertEqual(reading.revisions, ("0006_saved_history",))

    async def test_tables_built_without_alembic_have_no_version_table(self) -> None:
        await self.database.create_all()
        reading = await SqlSchemaRevisionReader(self.database).read()
        self.assertFalse(reading.table_present)


class FakeResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.value))


class FakePostgres:
    """A Database stand-in whose connection answers the reader's three
    queries from a table of results."""

    dialect = "postgresql"

    def __init__(self, *, present=True, allowed=True, rows=(EXPECTED_SCHEMA_REVISION,), error=None) -> None:
        self.answers = {"to_regclass": present, "has_table_privilege": allowed, "version_num": rows}
        self.error = error
        self.queries: list[str] = []

    def engine(self):
        return self

    @asynccontextmanager
    async def connect(self):
        if self.error:
            raise self.error
        yield self

    async def execute(self, statement):
        sql = str(statement)
        self.queries.append(sql)
        for marker, value in self.answers.items():
            if marker in sql:
                return FakeResult(value)
        raise AssertionError(sql)


class PostgresReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_the_revision(self) -> None:
        reading = await SqlSchemaRevisionReader(FakePostgres()).read()
        self.assertEqual(reading.revisions, (EXPECTED_SCHEMA_REVISION,))

    async def test_missing_table(self) -> None:
        database = FakePostgres(present=False)
        self.assertFalse((await SqlSchemaRevisionReader(database).read()).table_present)
        self.assertEqual(len(database.queries), 1)

    async def test_no_privilege_is_unreadable_without_querying_the_table(self) -> None:
        database = FakePostgres(allowed=False)
        reading = await SqlSchemaRevisionReader(database).read()
        self.assertFalse(reading.readable)
        self.assertFalse(any("version_num" in q for q in database.queries))

    async def test_rls_hiding_the_row_is_unreadable(self) -> None:
        self.assertFalse((await SqlSchemaRevisionReader(FakePostgres(rows=())).read()).readable)

    async def test_a_failed_connection_is_unreachable_and_never_raises(self) -> None:
        with self.assertLogs("videolens", level="ERROR") as logs:
            reading = await SqlSchemaRevisionReader(FakePostgres(error=OSError("password=hunter2"))).read()
        self.assertFalse(reading.reachable)
        # The class name only: driver text can carry the host or user.
        self.assertNotIn("hunter2", logs.output[0])


if __name__ == "__main__":
    unittest.main()
