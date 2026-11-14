"""Schema tightening (2026-11-14): migration 0007 (identity foreign keys
cascade). No Postgres in the suite: the Postgres branch is checked through
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

from app.infrastructure.persistence import schema

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
