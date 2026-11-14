"""Schema tightening (2026-11-14): migrations 0007 (identity foreign keys
cascade) and 0008 (fixed-value check constraints). No Postgres in the suite: the Postgres branch is checked through
the offline (`--sql`) render and with Alembic's `op` mocked; the SQLite round
trip checks the migration is a no-op there and downgrades cleanly."""

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import re

from sqlalchemy import CheckConstraint
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from app.domain.entities import AnalysisCompleteness, FreeRunPeriod, WorkspaceRole
from app.domain.policies import period_key
from app.infrastructure.persistence import billing_store, schema

BACKEND = Path(__file__).resolve().parents[3]


def _alembic_config(url: str):
    from alembic.config import Config

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


def _offline_sql(revisions: str) -> str:
    from alembic import command

    config = _alembic_config("postgresql+asyncpg://user:pw@db.invalid/videolens")
    out = io.StringIO()
    config.output_buffer = out
    with mock.patch.dict(os.environ, {"DATABASE_URL": "", "DATABASE_APP_ROLE": "videolens_api"}):
        with contextlib.redirect_stdout(io.StringIO()):
            command.upgrade(config, revisions, sql=True)
    return out.getvalue()


def _load(filename: str):
    path = BACKEND / "migrations" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mock_op(test: unittest.TestCase, module, dialect: str = "postgresql") -> mock.MagicMock:
    op = mock.MagicMock()
    op.get_bind.return_value.dialect.name = dialect
    patcher = mock.patch.object(module, "op", op)
    patcher.start()
    test.addCleanup(patcher.stop)
    return op


def _foreign_key(table, column: str):
    (fk,) = table.c[column].foreign_keys
    return fk


class IdentityCascadeTests(unittest.TestCase):
    """0007: the four identity keys cascade, in the migration and in `schema.py`."""

    def test_metadata_declares_the_cascade_under_the_postgres_names(self) -> None:
        migration = _load("0007_identity_cascades.py")
        tables = {t.name: t for t in schema.metadata.sorted_tables}
        for name, table, column, referenced in migration.KEYS:
            fk = _foreign_key(tables[table], column)
            self.assertEqual(fk.constraint.name, name)
            self.assertEqual(fk.ondelete, "CASCADE")
            self.assertEqual(fk.column.table.name, referenced)
        self.assertEqual(len(migration.KEYS), 4)

    def test_every_key_into_accounts_or_workspaces_cascades_except_the_default_workspace(self) -> None:
        for table in schema.metadata.sorted_tables:
            for fk in table.foreign_keys:
                if fk.parent.table.name == "accounts":
                    continue  # accounts.default_workspace_id: SET NULL (0009)
                self.assertEqual(fk.ondelete, "CASCADE", f"{table.name}.{fk.parent.name}")

    def test_offline_sql_drops_and_readds_each_key_with_cascade(self) -> None:
        sql = _offline_sql("0006_saved_history:0007_identity_cascades")
        self.assertIn("ALTER TABLE workspaces DROP CONSTRAINT workspaces_owner_account_id_fkey", sql)
        self.assertIn(
            "ALTER TABLE workspaces ADD CONSTRAINT workspaces_owner_account_id_fkey FOREIGN KEY(owner_account_id) "
            "REFERENCES accounts (id) ON DELETE CASCADE",
            sql,
        )
        self.assertIn(
            "ALTER TABLE api_keys ADD CONSTRAINT api_keys_workspace_id_fkey FOREIGN KEY(workspace_id) "
            "REFERENCES workspaces (id) ON DELETE CASCADE",
            sql,
        )
        self.assertEqual(sql.count("ON DELETE CASCADE"), 4)
        self.assertEqual(sql.count("DROP CONSTRAINT"), 4)
        self.assertIn("UPDATE alembic_version SET version_num='0007_identity_cascades'", sql)

    def test_downgrade_restores_the_keys_without_an_action(self) -> None:
        migration = _load("0007_identity_cascades.py")
        op = _mock_op(self, migration)
        migration.downgrade()
        self.assertEqual(op.drop_constraint.call_count, 4)
        for call in op.create_foreign_key.call_args_list:
            self.assertIsNone(call.kwargs["ondelete"])

    def test_sqlite_is_a_no_op(self) -> None:
        migration = _load("0007_identity_cascades.py")
        op = _mock_op(self, migration, dialect="sqlite")
        migration.upgrade()
        migration.downgrade()
        op.drop_constraint.assert_not_called()
        op.create_foreign_key.assert_not_called()


class ValueCheckTests(unittest.TestCase):
    """0008: the allowed lists match the code, and `schema.py` matches 0008."""

    def setUp(self) -> None:
        self.migration = _load("0008_value_checks.py")

    def test_allowed_lists_are_the_codes_enums(self) -> None:
        self.assertEqual(set(self.migration.WORKSPACE_ROLES), {r.value for r in WorkspaceRole})
        self.assertEqual(set(self.migration.COMPLETENESS), {c.value for c in AnalysisCompleteness})
        self.assertEqual(
            set(self.migration.EXTRA_RUN_STATES),
            {billing_store.HELD, billing_store.DUE, billing_store.REPORTED, billing_store.VOID},
        )

    def test_period_formats_accept_every_key_the_code_writes(self) -> None:
        from datetime import datetime, timezone

        now = datetime(2026, 1, 5, 23, 59, tzinfo=timezone.utc)
        day_or_month = re.compile(self.migration.DAY_OR_MONTH)
        month = re.compile(self.migration.MONTH)
        for period in FreeRunPeriod:
            self.assertRegex(period_key(period, now), day_or_month)
        self.assertRegex(period_key(FreeRunPeriod.MONTH, now), month)
        self.assertNotRegex(period_key(FreeRunPeriod.DAY, now), month)
        for bad in ("", "2026", "2026-1", "2026-11-1", "2026-11-14x", "abcd-ef"):
            self.assertNotRegex(bad, day_or_month)

    def test_extra_run_period_is_the_month_key(self) -> None:
        from datetime import datetime, timezone

        from app.application.billing import BillingPlans

        # Unbound call: `extra_runs_period` reads nothing from self when `now` is given.
        key = BillingPlans.extra_runs_period(object(), datetime(2026, 11, 14, tzinfo=timezone.utc))
        self.assertEqual(key, "2026-11")
        self.assertRegex(key, self.migration.MONTH)

    def test_schema_declares_every_check_with_the_same_condition(self) -> None:
        tables = {t.name: t for t in schema.metadata.sorted_tables}
        for name, table, condition in self.migration.CHECKS:
            checks = {c.name: c for c in tables[table].constraints if isinstance(c, CheckConstraint)}
            self.assertIn(name, checks, f"{table}: {name}")
            self.assertEqual(str(checks[name].sqltext), condition)

    def test_period_checks_are_postgres_only_in_the_test_schema(self) -> None:
        pg = str(CreateTable(schema.account_free_runs).compile(dialect=postgresql.dialect()))
        lite = str(CreateTable(schema.account_free_runs).compile(dialect=sqlite.dialect()))
        self.assertIn("ck_account_free_runs_period", pg)
        self.assertNotIn("ck_account_free_runs_period", lite)
        lite_members = str(CreateTable(schema.workspace_members).compile(dialect=sqlite.dialect()))
        self.assertIn("ck_workspace_members_role", lite_members)

    def test_no_constraint_on_the_stripe_columns(self) -> None:
        checks = [c for c in schema.billing_accounts.constraints if isinstance(c, CheckConstraint)]
        self.assertEqual(checks, [])
        self.assertFalse(any(table == "billing_accounts" for _, table, _ in self.migration.CHECKS))

    def test_offline_sql_adds_the_six_named_checks(self) -> None:
        sql = _offline_sql("0007_identity_cascades:0008_value_checks")
        self.assertIn(
            "ALTER TABLE workspace_members ADD CONSTRAINT ck_workspace_members_role CHECK (role IN ('owner', 'member'))",
            sql,
        )
        self.assertIn(
            "ALTER TABLE billing_extra_runs ADD CONSTRAINT ck_billing_extra_runs_period "
            "CHECK (period ~ '^[0-9]{4}-[0-9]{2}$')",
            sql,
        )
        self.assertEqual(sql.count("ADD CONSTRAINT ck_"), 6)
        self.assertNotIn("billing_accounts", sql)
        self.assertIn("UPDATE alembic_version SET version_num='0008_value_checks'", sql)

    def test_downgrade_drops_each_by_name_and_sqlite_is_a_no_op(self) -> None:
        op = _mock_op(self, self.migration)
        self.migration.downgrade()
        dropped = {call.args[0] for call in op.drop_constraint.call_args_list}
        self.assertEqual(dropped, {name for name, _, _ in self.migration.CHECKS})
        op.reset_mock()
        op.get_bind.return_value.dialect.name = "sqlite"
        self.migration.upgrade()
        self.migration.downgrade()
        op.create_check_constraint.assert_not_called()
        op.drop_constraint.assert_not_called()


class SqliteCheckEnforcementTests(unittest.IsolatedAsyncioTestCase):
    """The enum checks are portable, so the SQLite test schema enforces them."""

    async def test_an_unknown_role_is_rejected(self) -> None:
        from datetime import datetime, timezone

        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError

        from app.infrastructure.config import Settings
        from app.infrastructure.persistence.database import Database

        with tempfile.TemporaryDirectory() as tmp:
            url = f"sqlite:///{Path(tmp, 'checks.sqlite3').as_posix()}"
            database = Database(Settings(_env_file=None, gemini_api_key="k", database_url=url))
            try:
                await database.create_all()
                now = datetime(2026, 11, 14, tzinfo=timezone.utc)
                async with database.connect() as conn:
                    await conn.execute(insert(schema.accounts).values(id="a", external_id="s", created_at=now))
                    await conn.execute(
                        insert(schema.workspaces).values(id="w", name="n", owner_account_id="a", created_at=now)
                    )
                    await conn.execute(
                        insert(schema.workspace_members).values(workspace_id="w", account_id="a", role="owner")
                    )
                with self.assertRaises(IntegrityError):
                    async with database.connect() as conn:
                        await conn.execute(
                            insert(schema.workspace_members).values(workspace_id="w", account_id="b", role="admin")
                        )
            finally:
                await database.close()


class SqliteRoundTripTests(unittest.TestCase):
    def test_upgrade_head_and_back_to_0006_on_sqlite(self) -> None:
        from alembic import command
        from sqlalchemy import create_engine, inspect

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "migrate.sqlite3").as_posix()
            config = _alembic_config(f"sqlite+aiosqlite:///{path}")
            with mock.patch.dict(os.environ, {"DATABASE_URL": ""}):
                command.upgrade(config, "head")
                command.downgrade(config, "0006_saved_history")
                engine = create_engine(f"sqlite:///{path}")
                try:
                    self.assertIn("workspace_members", inspect(engine).get_table_names())
                finally:
                    engine.dispose()


if __name__ == "__main__":
    unittest.main()
