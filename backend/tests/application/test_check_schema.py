import unittest

from app.application.check_schema import CheckSchemaUseCase
from app.domain.errors import SchemaOutOfDateError
from app.domain.schema_revision import EXPECTED_SCHEMA_REVISION, SchemaReading, SchemaState


class FixedReader:
    def __init__(self, reading: SchemaReading) -> None:
        self.reading = reading
        self.reads = 0

    async def read(self) -> SchemaReading:
        self.reads += 1
        return self.reading


def check(reading: SchemaReading, *, enforce: bool = True) -> CheckSchemaUseCase:
    return CheckSchemaUseCase(reader=FixedReader(reading), enforce=enforce)


class CheckSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_behind_refuses_naming_both_revisions(self) -> None:
        use_case = check(SchemaReading(revisions=("0009_default_workspace_fk",)))
        with self.assertRaises(SchemaOutOfDateError) as raised:
            await use_case.run()
        self.assertIn("0009_default_workspace_fk", str(raised.exception))
        self.assertIn(EXPECTED_SCHEMA_REVISION, str(raised.exception))
        self.assertIs(use_case.last.state, SchemaState.BEHIND)

    async def test_missing_table_refuses(self) -> None:
        with self.assertRaisesRegex(SchemaOutOfDateError, "no alembic_version table"):
            await check(SchemaReading(table_present=False)).run()

    async def test_equal_is_ok(self) -> None:
        result = await check(SchemaReading(revisions=(EXPECTED_SCHEMA_REVISION,))).run()
        self.assertIs(result.state, SchemaState.OK)
        self.assertEqual(result.found, EXPECTED_SCHEMA_REVISION)

    async def test_ahead_warns_and_continues(self) -> None:
        with self.assertLogs("videolens", level="WARNING") as logs:
            result = await check(SchemaReading(revisions=("0099_newer",))).run()
        self.assertIs(result.state, SchemaState.AHEAD)
        self.assertIn("0099_newer", logs.output[0])
        self.assertIn("rollback", logs.output[0])

    async def test_unreadable_and_unreachable_log_an_error_and_continue(self) -> None:
        for reading, state in (
            (SchemaReading(readable=False), SchemaState.UNREADABLE),
            (SchemaReading(reachable=False), SchemaState.UNREACHABLE),
        ):
            with self.subTest(state=state), self.assertLogs("videolens", level="ERROR"):
                result = await check(reading).run()
            self.assertIs(result.state, state)

    async def test_sqlite_is_warned_not_refused(self) -> None:
        with self.assertLogs("videolens", level="WARNING"):
            result = await check(SchemaReading(table_present=False), enforce=False).run()
        self.assertIs(result.state, SchemaState.MISSING)

    async def test_no_database_is_skipped(self) -> None:
        use_case = CheckSchemaUseCase(reader=None, enforce=True)
        self.assertIsNone(use_case.last)
        result = await use_case.run()
        self.assertIs(result.state, SchemaState.DISABLED)
        self.assertIs(use_case.last, result)


if __name__ == "__main__":
    unittest.main()
