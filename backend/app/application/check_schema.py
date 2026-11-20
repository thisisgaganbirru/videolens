import logging
from dataclasses import dataclass

from ..domain.errors import SchemaOutOfDateError
from ..domain.ports import SchemaRevisionReader
from ..domain.schema_revision import EXPECTED_SCHEMA_REVISION, SchemaState, compare_schema

logger = logging.getLogger("videolens")


@dataclass(frozen=True)
class SchemaCheck:
    state: SchemaState
    expected: str
    found: str | None = None


class CheckSchemaUseCase:
    """Compares the database's recorded schema revision with the one this
    code expects, once at startup of the API and of the worker
    (docs/backend/startup-checks.md).

    Behind, or never migrated: refused (`SchemaOutOfDateError`) when
    `enforce`, so new code never serves against a schema it would fail on.
    A revision the code does not know is logged and allowed: older code
    against a newer, additive schema is what a rollback looks like. When the
    revision cannot be read (no privilege on `alembic_version`, RLS, the
    database down) the check cannot decide, so it says so at ERROR and lets
    the process start: anonymous use does not need the database.
    `enforce` is False for SQLite, which is local use only and may have been
    built without Alembic. No reader (no `DATABASE_URL`): nothing to check.
    """

    def __init__(self, *, reader: SchemaRevisionReader | None, enforce: bool) -> None:
        self._reader = reader
        self._enforce = enforce
        # The last result, for the readiness probe. None until run once.
        self.last: SchemaCheck | None = None

    async def run(self) -> SchemaCheck:
        if self._reader is None:
            result = SchemaCheck(state=SchemaState.DISABLED, expected=EXPECTED_SCHEMA_REVISION)
            self.last = result
            return result
        state, found = compare_schema(await self._reader.read())
        result = SchemaCheck(state=state, expected=EXPECTED_SCHEMA_REVISION, found=found)
        self.last = result
        expected = EXPECTED_SCHEMA_REVISION
        if state is SchemaState.OK:
            logger.info("Database schema is at %s, as this code expects", found)
        elif state in (SchemaState.BEHIND, SchemaState.MISSING):
            message = (
                f"The database schema is at {found}, but this code expects {expected}."
                if state is SchemaState.BEHIND
                else f"The database has no alembic_version table, but this code expects schema {expected}."
            ) + " Apply the migrations (`alembic upgrade head`, DEPLOYMENT.md \"Release checklist\") before this version serves traffic."
            if self._enforce:
                raise SchemaOutOfDateError(message)
            logger.warning("%s Not refused on SQLite.", message)
        elif state is SchemaState.AHEAD:
            logger.warning(
                "The database schema is at %s, which this code does not know (it expects %s). Continuing: "
                "this is normally older code running against a newer schema after a rollback.",
                found,
                expected,
            )
        elif state is SchemaState.UNREADABLE:
            logger.error(
                "Could not read the database schema revision (alembic_version is not readable by this "
                "role, or has no row), so the schema check cannot protect this deployment. Grant the "
                "backend role SELECT on alembic_version (DEPLOYMENT.md \"Release checklist\"). Expected %s.",
                expected,
            )
        else:
            logger.error(
                "The database did not answer at startup, so the schema was not checked (expected %s). "
                "Anonymous use continues; signed-in routes fail until it answers.",
                expected,
            )
        return result
