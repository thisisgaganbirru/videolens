"""The SavedRunRepository adapters (docs/backend/saved-history.md): SQL
(SQLite through aiosqlite, standing in for Postgres) and in-memory share
one behaviour suite. Also: the SQL deletion hold (schedule, restore,
due-for-purge, removal for good), and migration 0006 (SQLite round trip,
offline Postgres SQL, Postgres branch with Alembic mocked)."""

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy import inspect

from app.domain.entities import SavedRun, SavedRunSource, SubscriptionSnapshot
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_deleter import SqlAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory, SqlAccountDirectory
from app.infrastructure.persistence.billing_store import SqlBillingAccounts
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.identity_users import AlwaysPresentIdentityProviderUsers
from app.infrastructure.persistence.saved_run_repository import InMemorySavedRuns, SqlSavedRuns

BACKEND = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, gemini_api_key="k", **overrides)


def _saved(account_id: str, run_id: str, minutes_ago: int = 0) -> SavedRun:
    return SavedRun(
        run_id=run_id,
        account_id=account_id,
        title=f"Title {run_id}",
        summary_snippet="A summary.",
        source=SavedRunSource(source_kind="link", platform="youtube", source_url="https://youtu.be/x"),
        result={"title": f"Title {run_id}", "summary": "A summary.", "transcript": "words", "markdown": "# T"},
        completeness="full",
        created_at=NOW - timedelta(minutes=minutes_ago),
    )


class _Behaviour:
    """Mixed into a TestCase whose asyncSetUp sets repo, account_id, other_id."""

    async def test_save_is_idempotent_per_account_and_run(self) -> None:
        self.assertTrue(await self.repo.save(_saved(self.account_id, "run-1")))
        self.assertFalse(await self.repo.save(_saved(self.account_id, "run-1")))
        # The same run id under another account is its own row.
        self.assertTrue(await self.repo.save(_saved(self.other_id, "run-1")))
        self.assertEqual(await self.repo.count(self.account_id), 1)

    async def test_get_round_trips_the_document(self) -> None:
        await self.repo.save(_saved(self.account_id, "run-1"))
        saved = await self.repo.get(self.account_id, "run-1")
        self.assertEqual(saved.result["transcript"], "words")
        self.assertEqual(saved.source.platform, "youtube")
        self.assertEqual(saved.created_at, NOW)
        self.assertIsNone(await self.repo.get(self.other_id, "run-1"))

    async def test_keyset_pages_newest_first(self) -> None:
        for index in range(5):
            await self.repo.save(_saved(self.account_id, f"run-{index}", minutes_ago=index))
        await self.repo.save(_saved(self.other_id, "theirs"))
        seen, before = [], None
        while True:
            page = await self.repo.list_page(self.account_id, limit=2, before=before)
            seen.extend(item.run_id for item in page.items)
            if page.next_cursor is None:
                break
            before = page.next_cursor
        self.assertEqual(seen, [f"run-{i}" for i in range(5)])

    async def test_ties_on_created_at_still_page_exactly_once(self) -> None:
        for index in range(4):
            await self.repo.save(_saved(self.account_id, f"run-{index}"))
        first = await self.repo.list_page(self.account_id, limit=2)
        second = await self.repo.list_page(self.account_id, limit=2, before=first.next_cursor)
        ids = [i.run_id for i in first.items + second.items]
        self.assertEqual(sorted(ids), [f"run-{i}" for i in range(4)])
        self.assertIsNone(second.next_cursor)

    async def test_delete_is_scoped_to_the_account(self) -> None:
        await self.repo.save(_saved(self.account_id, "run-1"))
        await self.repo.save(_saved(self.account_id, "run-2"))
        self.assertFalse(await self.repo.delete(self.other_id, "run-1"))
        self.assertTrue(await self.repo.delete(self.account_id, "run-1"))
        self.assertFalse(await self.repo.delete(self.account_id, "run-1"))
        self.assertEqual(await self.repo.delete_all(self.other_id), 0)
        self.assertEqual(await self.repo.delete_all(self.account_id), 1)

    async def test_expiry_arms_once_replaces_on_request_and_clears(self) -> None:
        first = await self.repo.arm_expiry(self.account_id, NOW + timedelta(days=30))
        self.assertEqual(first, NOW + timedelta(days=30))
        self.assertEqual(await self.repo.arm_expiry(self.account_id, NOW + timedelta(days=40)), first)
        replaced = await self.repo.arm_expiry(self.account_id, NOW + timedelta(days=40), replace=True)
        self.assertEqual(replaced, NOW + timedelta(days=40))
        await self.repo.clear_expiry(self.account_id)
        self.assertIsNone(await self.repo.expiry(self.account_id))

    async def test_purge_only_after_the_expiry(self) -> None:
        await self.repo.save(_saved(self.account_id, "run-1"))
        await self.repo.save(_saved(self.other_id, "run-1"))
        await self.repo.arm_expiry(self.account_id, NOW + timedelta(days=30))
        self.assertEqual(await self.repo.expired_accounts(NOW, limit=10), [])
        self.assertEqual(await self.repo.purge_expired(self.account_id, NOW), 0)
        later = NOW + timedelta(days=31)
        self.assertEqual(await self.repo.expired_accounts(later, limit=10), [self.account_id])
        self.assertEqual(await self.repo.purge_expired(self.account_id, later), 1)
        self.assertEqual(await self.repo.purge_expired(self.account_id, later), 0)
        self.assertIsNone(await self.repo.expiry(self.account_id))
        self.assertEqual(await self.repo.count(self.other_id), 1)


class SqlSavedRunsTests(_Behaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = _settings(database_url="sqlite://")
        self.database = Database(self.settings)
        self.addAsyncCleanup(self.database.close)
        await self.database.create_all()
        self.directory = SqlAccountDirectory(
            self.database, users=AlwaysPresentIdentityProviderUsers(self.settings)
        )
        self.account_id = (await self.directory.resolve_account("sub-1", "a@b.test")).account_id
        self.other_id = (await self.directory.resolve_account("sub-2", "c@d.test")).account_id
        self.repo = SqlSavedRuns(self.settings, self.database)
        self.billing = SqlBillingAccounts(self.settings, self.database, clock=lambda: NOW)
        self.deleter = SqlAccountDeleter(self.settings, self.database)

    async def _subscription(self, account_id: str, status: str, end: datetime) -> None:
        await self.billing.link_customer(account_id, f"cus_{account_id}")
        await self.billing.apply_subscription(
            account_id,
            SubscriptionSnapshot(
                subscription_id=f"sub_{account_id}",
                customer_id=f"cus_{account_id}",
                status=status,
                price_id="price_m",
                interval="month",
                current_period_end=end,
                cancel_at_period_end=False,
            ),
        )

    async def test_accounts_to_arm_skips_paid_unsettled_armed_empty_and_held(self) -> None:
        third = (await self.directory.resolve_account("sub-3")).account_id
        fourth = (await self.directory.resolve_account("sub-4")).account_id
        fifth = (await self.directory.resolve_account("sub-5")).account_id
        lapsed = (await self.directory.resolve_account("sub-6")).account_id
        for account_id in (self.account_id, self.other_id, third, fourth, fifth, lapsed):
            await self.repo.save(_saved(account_id, "run-1"))
        await self._subscription(self.account_id, "canceled", NOW - timedelta(days=1))  # ended: armed
        await self._subscription(self.other_id, "active", NOW + timedelta(days=10))  # paid
        await self._subscription(third, "past_due", NOW + timedelta(days=10))  # unsettled
        await self.repo.arm_expiry(fourth, NOW + timedelta(days=5))  # already armed
        await self.deleter.schedule_deletion("sub-5", now=NOW, purge_at=NOW + timedelta(days=30))  # held
        await self._subscription(lapsed, "active", NOW - timedelta(days=10))  # period long over
        empty = (await self.directory.resolve_account("sub-7")).account_id  # no saved runs

        candidates = set(await self.repo.accounts_to_arm(NOW, limit=50))

        self.assertEqual(candidates, {self.account_id, lapsed})
        self.assertNotIn(empty, candidates)

    async def test_the_hold_schedules_restores_and_removes_for_good(self) -> None:
        await self.repo.save(_saved(self.account_id, "run-1"))
        purge_at = NOW + timedelta(days=30)
        self.assertEqual(await self.deleter.schedule_deletion("sub-1", now=NOW, purge_at=purge_at), purge_at)
        # A repeat keeps the first deadline; an unknown subject has none.
        later = purge_at + timedelta(days=9)
        self.assertEqual(await self.deleter.schedule_deletion("sub-1", now=NOW, purge_at=later), purge_at)
        self.assertIsNone(await self.deleter.schedule_deletion("nobody", now=NOW, purge_at=purge_at))
        held = await self.directory.resolve_account("sub-1")
        self.assertTrue(held.pending_deletion)
        self.assertEqual((held.deleted_at, held.purge_at), (NOW, purge_at))

        self.assertTrue(await self.deleter.restore("sub-1", now=NOW + timedelta(days=1)))
        self.assertFalse(await self.deleter.restore("sub-1", now=NOW + timedelta(days=1)))
        self.assertFalse((await self.directory.resolve_account("sub-1")).pending_deletion)

        await self.deleter.schedule_deletion("sub-1", now=NOW, purge_at=purge_at)
        self.assertIsNone(await self.deleter.restore("sub-1", now=purge_at))  # too late
        self.assertEqual(await self.deleter.due_for_purge(purge_at - timedelta(seconds=1), limit=10), [])
        due = await self.deleter.due_for_purge(purge_at, limit=10)
        self.assertEqual([(d.account_id, d.external_id) for d in due], [(self.account_id, "sub-1")])

        self.assertFalse(await self.deleter.delete_account("sub-1", due_before=purge_at - timedelta(seconds=1)))
        self.assertTrue(await self.deleter.delete_account("sub-1", due_before=purge_at))
        self.assertEqual(await self.repo.count(self.account_id), 0)
        self.assertNotEqual((await self.directory.resolve_account("sub-1")).account_id, self.account_id)

    async def test_a_held_account_is_not_purged_by_its_window(self) -> None:
        await self.repo.save(_saved(self.account_id, "run-1"))
        await self.repo.arm_expiry(self.account_id, NOW)
        await self.deleter.schedule_deletion("sub-1", now=NOW, purge_at=NOW + timedelta(days=30))
        self.assertEqual(await self.repo.expired_accounts(NOW + timedelta(days=1), limit=10), [])
        self.assertEqual(await self.repo.purge_expired(self.account_id, NOW + timedelta(days=1)), 0)
        self.assertEqual(await self.repo.count(self.account_id), 1)


class InMemorySavedRunsTests(_Behaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = InMemoryAccountDirectory()
        self.account_id = (await self.directory.resolve_account("sub-1")).account_id
        self.other_id = (await self.directory.resolve_account("sub-2")).account_id
        self.repo = InMemorySavedRuns(_settings(), accounts=self.directory)

    async def test_a_held_account_is_not_purged_by_its_window(self) -> None:
        await self.repo.save(_saved(self.account_id, "run-1"))
        await self.repo.arm_expiry(self.account_id, NOW)
        self.directory.schedule_deletion("sub-1", NOW, NOW + timedelta(days=30))
        self.assertEqual(await self.repo.expired_accounts(NOW + timedelta(days=1), limit=10), [])
        self.assertEqual(await self.repo.purge_expired(self.account_id, NOW + timedelta(days=1)), 0)


def _alembic_config(url: str):
    from alembic.config import Config

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


class AlembicSavedHistoryTests(unittest.TestCase):
    def test_upgrade_and_downgrade_on_sqlite(self) -> None:
        from alembic import command
        from sqlalchemy import create_engine

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "migrate.sqlite3").as_posix()
            config = _alembic_config(f"sqlite+aiosqlite:///{path}")
            with mock.patch.dict(os.environ, {"DATABASE_URL": ""}):
                command.upgrade(config, "head")
                engine = create_engine(f"sqlite:///{path}")
                try:
                    inspector = inspect(engine)
                    self.assertIn("saved_runs", inspector.get_table_names())
                    fk = inspector.get_foreign_keys("saved_runs")[0]
                    self.assertEqual((fk["referred_table"], fk["options"].get("ondelete")), ("accounts", "CASCADE"))
                    unique = {tuple(u["column_names"]) for u in inspector.get_unique_constraints("saved_runs")}
                    self.assertIn(("account_id", "run_id"), unique)
                    columns = {c["name"] for c in inspector.get_columns("accounts")}
                    self.assertTrue({"deleted_at", "purge_at", "saved_runs_expire_at"} <= columns)
                    indexes = {i["name"] for i in inspector.get_indexes("accounts")}
                    self.assertTrue({"ix_accounts_purge_at", "ix_accounts_saved_runs_expire_at"} <= indexes)

                    command.downgrade(config, "0005_account_daily_free_runs")
                    inspector = inspect(engine)
                    self.assertNotIn("saved_runs", inspector.get_table_names())
                    columns = {c["name"] for c in inspector.get_columns("accounts")}
                    self.assertFalse({"deleted_at", "purge_at", "saved_runs_expire_at"} & columns)
                finally:
                    engine.dispose()

    def test_offline_postgres_sql_renders_the_table_rls_and_grants(self) -> None:
        """`alembic upgrade 0005:0006 --sql`, no database touched."""
        from alembic import command

        config = _alembic_config("postgresql+asyncpg://user:pw@db.invalid/videolens")
        out = io.StringIO()
        config.output_buffer = out
        with mock.patch.dict(os.environ, {"DATABASE_URL": "", "DATABASE_APP_ROLE": "videolens_api"}):
            with contextlib.redirect_stdout(io.StringIO()):
                command.upgrade(config, "0005_account_daily_free_runs:0006_saved_history", sql=True)
        sql = out.getvalue()
        self.assertIn("ALTER TABLE accounts ADD COLUMN purge_at TIMESTAMP WITH TIME ZONE", sql)
        self.assertIn("CREATE TABLE saved_runs", sql)
        self.assertIn("result JSONB NOT NULL", sql)
        self.assertIn("CONSTRAINT uq_saved_runs_account_run UNIQUE (account_id, run_id)", sql)
        self.assertIn("ON DELETE CASCADE", sql)
        self.assertIn("ALTER TABLE public.saved_runs ENABLE ROW LEVEL SECURITY", sql)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON public.saved_runs TO videolens_api", sql)
        self.assertIn("CREATE POLICY videolens_api_all ON public.saved_runs", sql)
        self.assertIn("UPDATE alembic_version SET version_num='0006_saved_history'", sql)


def _load_migration():
    path = BACKEND / "migrations" / "versions" / "0006_saved_history.py"
    spec = importlib.util.spec_from_file_location("migration_0006_saved_history", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PostgresMigrationPathTests(unittest.TestCase):
    """0006's Postgres branch with Alembic mocked (no Postgres in the suite)."""

    def setUp(self) -> None:
        self.migration = _load_migration()
        self.op = mock.MagicMock()
        self.op.get_bind.return_value.dialect.name = "postgresql"
        self.context = mock.MagicMock()
        self.context.is_offline_mode.return_value = False
        for name, value in (("op", self.op), ("context", self.context)):
            patcher = mock.patch.object(self.migration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"DATABASE_APP_ROLE": "videolens_api"})
        env.start()
        self.addCleanup(env.stop)

    def test_a_missing_role_fails_before_anything_changes(self) -> None:
        self.op.get_bind.return_value.execute.return_value.scalar.return_value = None
        with self.assertRaises(RuntimeError):
            self.migration.upgrade()
        self.op.add_column.assert_not_called()
        self.op.create_table.assert_not_called()

    def test_rejects_a_role_name_that_is_not_a_plain_identifier(self) -> None:
        with mock.patch.dict(os.environ, {"DATABASE_APP_ROLE": "x; DROP TABLE accounts"}):
            with self.assertRaises(ValueError):
                self.migration.upgrade()


if __name__ == "__main__":
    unittest.main()
