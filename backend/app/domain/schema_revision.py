"""Which database schema this code expects, and how a database's recorded
revision compares with it.

The schema belongs to Alembic (`backend/migrations/`), but the image ships
only `app/`, so the migrations directory is not there to ask at runtime.
These two constants are the code's own record of the chain instead;
`tests/domain/test_schema_revision.py` fails when they drift from
`backend/migrations/versions/`, so a new migration cannot ship without
bumping them.
"""

from dataclasses import dataclass
from enum import Enum

# Every revision the code knows, oldest first. A database at any of these
# but the last is behind the code.
KNOWN_SCHEMA_REVISIONS: tuple[str, ...] = (
    "0001_identity",
    "0002_auth_user_deleter",
    "0003_account_free_runs",
    "0004_billing",
    "0005_account_daily_free_runs",
    "0006_saved_history",
    "0007_identity_cascades",
    "0008_value_checks",
    "0009_default_workspace_fk",
    "0010_complimentary_plus",
)

# The head this code reads and writes against.
EXPECTED_SCHEMA_REVISION = KNOWN_SCHEMA_REVISIONS[-1]


@dataclass(frozen=True)
class SchemaReading:
    """What the database itself says, before any comparison.

    `reachable` False: the query did not get an answer at all.
    `table_present` False: there is no `alembic_version` table.
    `readable` False: the table is there, but this role may not read it, or
    reading it returned no row (Supabase turns on RLS for the table, so a
    role without a policy sees it empty). `revisions` holds what was read.
    """

    reachable: bool = True
    table_present: bool = True
    readable: bool = True
    revisions: tuple[str, ...] = ()


class SchemaState(str, Enum):
    DISABLED = "disabled"  # no DATABASE_URL: nothing to check
    OK = "ok"
    BEHIND = "behind"  # an older known revision: migrate before this code serves
    MISSING = "missing"  # no alembic_version table: never migrated
    AHEAD = "ahead"  # a revision this code does not know: a rollback, normally
    UNREADABLE = "unreadable"  # cannot tell (no privilege, RLS, no row)
    UNREACHABLE = "unreachable"  # the database did not answer


def compare_schema(reading: SchemaReading) -> tuple[SchemaState, str | None]:
    """The state of a reading against EXPECTED_SCHEMA_REVISION, and the
    revision found (None when none could be read).

    Alembic keeps one row per head; this chain is linear, so there is one.
    Should a database ever hold several, the oldest known one decides, since
    that is the part of the schema the code could find missing.
    """
    if not reading.reachable:
        return SchemaState.UNREACHABLE, None
    if not reading.table_present:
        return SchemaState.MISSING, None
    if not reading.readable or not reading.revisions:
        return SchemaState.UNREADABLE, None
    known = [r for r in reading.revisions if r in KNOWN_SCHEMA_REVISIONS]
    if len(known) < len(reading.revisions):
        unknown = next(r for r in reading.revisions if r not in KNOWN_SCHEMA_REVISIONS)
        return SchemaState.AHEAD, unknown
    oldest = min(known, key=KNOWN_SCHEMA_REVISIONS.index)
    if oldest == EXPECTED_SCHEMA_REVISION:
        return SchemaState.OK, oldest
    return SchemaState.BEHIND, oldest
