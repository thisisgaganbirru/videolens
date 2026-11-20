"""`schema.py` (what the app and the test databases are built from) against
the Alembic chain (what production runs). The chain is upgraded to head on
an SQLite file and Alembic's own autogenerate comparison is run against the
metadata, with type and server-default comparison on: a column, type,
length, nullability, index or default added on one side only shows up as a
difference here.

Known differences are listed by name, each with its reason; anything else
fails, so a migration and a `schema.py` edit have to land together. Limits:
SQLite reflects types coarsely (a String length is compared, a Postgres-only
type is not), and the Postgres-only parts (roles, SECURITY DEFINER helpers,
check constraints, the foreign-key actions) are covered by
`test_schema_tightening.py` through the offline render instead."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.infrastructure.persistence.schema import metadata

BACKEND = Path(__file__).resolve().parents[3]

# Columns whose default lives in the database (migration `server_default`)
# while `schema.py` gives a Python-side `default=`. Both fill the same value
# on every insert the app makes; only a hand-written SQL insert sees the
# difference. (table, column)
PYTHON_SIDE_DEFAULTS = {
    ("account_free_runs", "used"),
    ("api_keys", "active"),
    ("billing_accounts", "cancel_at_period_end"),
    ("workspace_members", "role"),
}

# Foreign keys 0007 (ON DELETE CASCADE) and 0009 (the named
# `accounts.default_workspace_id` key) rewrite on Postgres only; on SQLite
# those migrations are no-ops, so the reflected keys lack the action and the
# name. (table, constrained columns)
POSTGRES_ONLY_FOREIGN_KEYS = {
    ("accounts", ("default_workspace_id",)),
    ("api_keys", ("workspace_id",)),
    ("workspace_members", ("account_id",)),
    ("workspace_members", ("workspace_id",)),
    ("workspaces", ("owner_account_id",)),
}


def _flatten(diffs) -> list:
    """Column-level changes come grouped in lists; table-level ones are tuples."""
    flat = []
    for diff in diffs:
        flat.extend(diff if isinstance(diff, list) else [diff])
    return flat


def _known(diff) -> bool:
    kind = diff[0]
    if kind == "modify_default":
        _, _schema, table, column, _existing, _db_default, _model_default = diff
        return (table, column) in PYTHON_SIDE_DEFAULTS
    if kind in ("add_fk", "remove_fk"):
        constraint = diff[1]
        columns = tuple(column.name for column in constraint.columns)
        return (constraint.table.name, columns) in POSTGRES_ONLY_FOREIGN_KEYS
    return False


class SchemaMigrationDriftTests(unittest.TestCase):
    def _differences(self, target=metadata) -> list:
        from alembic import command
        from alembic.autogenerate import compare_metadata
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from sqlalchemy import create_engine

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "drift.sqlite3").as_posix()
            config = Config(str(BACKEND / "alembic.ini"))
            config.set_main_option("script_location", str(BACKEND / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
            config.attributes["configure_logger"] = False
            with mock.patch.dict(os.environ, {"DATABASE_URL": ""}):
                command.upgrade(config, "head")
            engine = create_engine(f"sqlite:///{path}")
            try:
                with engine.connect() as connection:
                    context = MigrationContext.configure(
                        connection, opts={"compare_type": True, "compare_server_default": True}
                    )
                    return _flatten(compare_metadata(context, target))
            finally:
                engine.dispose()

    def test_the_migrated_schema_matches_schema_py(self) -> None:
        unexpected = [diff for diff in self._differences() if not _known(diff)]
        self.assertEqual(unexpected, [], "schema.py and the migration chain disagree")

    def test_every_listed_difference_still_exists(self) -> None:
        # Fixing one on either side should also shorten the list above.
        found_defaults = {(d[2], d[3]) for d in self._differences() if d[0] == "modify_default"}
        self.assertEqual(found_defaults, PYTHON_SIDE_DEFAULTS)

    def test_a_drift_is_detected(self) -> None:
        # The comparison itself works: a column only the model has is
        # reported. Done on a copy, so the shared metadata is untouched.
        from sqlalchemy import Column, Integer, MetaData

        copy = MetaData()
        for table in metadata.sorted_tables:
            table.to_metadata(copy)
        copy.tables["api_keys"].append_column(Column("drift_probe", Integer, nullable=True))
        added = [diff for diff in self._differences(copy) if diff[0] == "add_column"]
        self.assertEqual([(diff[2], diff[3].name) for diff in added], [("api_keys", "drift_probe")])


if __name__ == "__main__":
    unittest.main()
