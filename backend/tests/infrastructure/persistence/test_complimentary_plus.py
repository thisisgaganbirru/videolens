"""Complimentary Plus storage (docs/backend/billing.md): migration 0010
(`accounts.complimentary_plus BOOLEAN NOT NULL DEFAULT false`), `schema.py`
in step, the SQL account directory reading it, `BillingPlans` over the real
SQL adapters (SQLite standing in for Postgres), and the saved-history scan
skipping it. The flag is written here with plain SQL, as the owner does."""

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, inspect, text, update

from app.application.billing import BillingPlans
from app.infrastructure.config import Settings
from app.infrastructure.persistence import schema
from app.infrastructure.persistence.account_directory import SqlAccountDirectory
from app.infrastructure.persistence.billing_store import SqlBillingAccounts, SqlExtraRunLedger
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.identity_users import AlwaysPresentIdentityProviderUsers
from app.infrastructure.persistence.saved_run_repository import SqlSavedRuns

from .test_saved_run_repository import NOW, _saved

BACKEND = Path(__file__).resolve().parents[3]


class _StripeOff:
    enabled = False


def _load():
    path = BACKEND / "migrations" / "versions" / "0010_complimentary_plus.py"
    spec = importlib.util.spec_from_file_location("migration_0010_complimentary_plus", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alembic_config(url: str):
    from alembic.config import Config

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


class SqlComplimentaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = Settings(_env_file=None, gemini_api_key="k", database_url="sqlite://")
        self.database = Database(self.settings)
        self.addAsyncCleanup(self.database.close)
        await self.database.create_all()
        self.directory = SqlAccountDirectory(self.database, users=AlwaysPresentIdentityProviderUsers(self.settings))
        self.mine = (await self.directory.resolve_account("sub-1")).account_id
        self.other = (await self.directory.resolve_account("sub-2")).account_id

    async def _grant(self, account_id: str, value: bool = True) -> None:
        async with self.database.connect() as conn:
            await conn.execute(
                update(schema.accounts).where(schema.accounts.c.id == account_id).values(complimentary_plus=value)
            )

    async def test_defaults_false_and_reads_back(self) -> None:
        self.assertFalse((await self.directory.get_account(self.mine)).complimentary_plus)
        await self._grant(self.mine)
        self.assertTrue((await self.directory.get_account(self.mine)).complimentary_plus)
        self.assertTrue((await self.directory.resolve_account("sub-1")).complimentary_plus)
        self.assertFalse((await self.directory.get_account(self.other)).complimentary_plus)

    async def test_billing_plans_with_stripe_off(self) -> None:
        plans = BillingPlans(
            gateway=_StripeOff(),
            accounts=SqlBillingAccounts(self.settings, self.database),
            ledger=SqlExtraRunLedger(self.settings, self.database),
            paid_runs_per_day=30,
            directory=self.directory,
        )
        self.assertFalse(plans.enabled)
        self.assertTrue(plans.offered)
        await self._grant(self.mine)
        mine = await plans.standing(self.mine)
        self.assertEqual((mine.paid, mine.complimentary, mine.billable), (True, True, False))
        self.assertFalse((await plans.standing(self.other)).paid)
        await self._grant(self.mine, False)
        self.assertFalse((await plans.standing(self.mine)).paid)

    async def test_the_window_scan_skips_complimentary_accounts(self) -> None:
        repo = SqlSavedRuns(self.settings, self.database)
        for account_id in (self.mine, self.other):
            await repo.save(_saved(account_id, "run-1"))
        await self._grant(self.mine)
        self.assertEqual(await repo.accounts_to_arm(NOW, limit=10), [self.other])


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.migration = _load()

    def test_schema_matches_the_migration(self) -> None:
        column = schema.accounts.c[self.migration.COLUMN]
        self.assertFalse(column.nullable)
        self.assertEqual(str(column.server_default.arg), "false")
        self.assertEqual(self.migration.down_revision, "0009_default_workspace_fk")

    def test_offline_postgres_sql(self) -> None:
        from alembic import command

        config = _alembic_config("postgresql+asyncpg://user:pw@db.invalid/videolens")
        out = io.StringIO()
        config.output_buffer = out
        with mock.patch.dict(os.environ, {"DATABASE_URL": "", "DATABASE_APP_ROLE": "videolens_api"}):
            with contextlib.redirect_stdout(io.StringIO()):
                command.upgrade(config, "0009_default_workspace_fk:0010_complimentary_plus", sql=True)
        sql = out.getvalue()
        self.assertIn("ALTER TABLE accounts ADD COLUMN complimentary_plus BOOLEAN DEFAULT false NOT NULL", sql)
        self.assertIn("UPDATE alembic_version SET version_num='0010_complimentary_plus'", sql)

    def test_sqlite_upgrade_defaults_existing_rows_and_downgrades(self) -> None:
        from alembic import command

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "migrate.sqlite3").as_posix()
            config = _alembic_config(f"sqlite+aiosqlite:///{path}")
            with mock.patch.dict(os.environ, {"DATABASE_URL": ""}):
                command.upgrade(config, "0009_default_workspace_fk")
                engine = create_engine(f"sqlite:///{path}")
                try:
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "INSERT INTO accounts (id, external_id, created_at) "
                                "VALUES ('a1', 'sub-1', :now)"
                            ),
                            {"now": datetime.now(timezone.utc) - timedelta(days=1)},
                        )
                    command.upgrade(config, "0010_complimentary_plus")
                    with engine.connect() as conn:
                        value = conn.execute(text("SELECT complimentary_plus FROM accounts WHERE id = 'a1'")).scalar()
                    self.assertEqual(value, 0)
                    command.downgrade(config, "0009_default_workspace_fk")
                    columns = {c["name"] for c in inspect(engine).get_columns("accounts")}
                    self.assertNotIn("complimentary_plus", columns)
                    self.assertIn("saved_runs_expire_at", columns)
                finally:
                    engine.dispose()


if __name__ == "__main__":
    unittest.main()
