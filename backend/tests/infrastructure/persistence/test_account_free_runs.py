"""The AccountFreeRunAllowance adapters (signed-in free runs, per account per
UTC month): SQL (SQLite through aiosqlite, standing in for Postgres) and
in-memory share one behaviour suite, so their rules cannot drift apart.
Also: account deletion clears the usage, and migration 0003."""

import asyncio
import importlib.util
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy import func, insert, inspect, select

from app.domain.entities import AccountFreeRunClaim, FreeRunScope
from app.domain.policies import start_of_next_utc_month, utc_month
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_deleter import InMemoryAccountDeleter, SqlAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory, SqlAccountDirectory
from app.infrastructure.persistence.account_free_runs import InMemoryAccountFreeRuns, SqlAccountFreeRuns
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.identity_users import AlwaysPresentIdentityProviderUsers
from app.infrastructure.persistence.schema import account_free_run_holds, account_free_runs

BACKEND = Path(__file__).resolve().parents[3]


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, gemini_api_key="k", **overrides)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class PolicyTests(unittest.TestCase):
    def test_month_and_next_month(self) -> None:
        self.assertEqual(utc_month(datetime(2026, 11, 30, 23, 59, tzinfo=timezone.utc)), "2026-11")
        self.assertEqual(
            start_of_next_utc_month(datetime(2026, 11, 13, 8, tzinfo=timezone.utc)),
            datetime(2026, 12, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(
            start_of_next_utc_month(datetime(2026, 12, 31, 23, tzinfo=timezone.utc)),
            datetime(2027, 1, 1, tzinfo=timezone.utc),
        )
        # A non-UTC instant counts by its UTC month.
        east = timezone(timedelta(hours=5))
        self.assertEqual(utc_month(datetime(2026, 12, 1, 2, tzinfo=east)), "2026-11")


class _AllowanceBehaviour:
    """Mixed into a TestCase whose asyncSetUp sets self.clock, self.store
    (limit 10), self.account_id and implements `_make(limit)`."""

    async def test_counts_up_to_the_limit_then_refuses(self) -> None:
        for _ in range(10):
            self.assertIsNotNone(await self.store.try_consume(self.account_id))
        self.assertIsNone(await self.store.try_consume(self.account_id))
        status = await self.store.status(self.account_id)
        self.assertEqual((status.enabled, status.limit, status.used, status.remaining), (True, 10, 10, 0))
        self.assertEqual(status.scope, FreeRunScope.ACCOUNT)
        self.assertEqual(status.resets_at, datetime(2026, 12, 1, tzinfo=timezone.utc))

    async def test_status_is_read_only(self) -> None:
        for _ in range(3):
            status = await self.store.status(self.account_id)
        self.assertEqual((status.used, status.remaining), (0, 10))

    async def test_a_new_month_is_a_fresh_allowance(self) -> None:
        for _ in range(10):
            await self.store.try_consume(self.account_id)
        self.clock.now = datetime(2026, 12, 1, 0, 0, 1, tzinfo=timezone.utc)
        self.assertEqual((await self.store.status(self.account_id)).used, 0)
        claim = await self.store.try_consume(self.account_id)
        self.assertEqual(claim, AccountFreeRunClaim(account_id=self.account_id, period="2026-12"))

    async def test_a_refund_after_the_month_turns_goes_to_the_claims_month(self) -> None:
        claim = await self.store.try_consume(self.account_id)
        self.clock.now = datetime(2026, 12, 2, tzinfo=timezone.utc)
        await self.store.try_consume(self.account_id)
        await self.store.refund(claim)
        self.assertEqual((await self.store.status(self.account_id)).used, 1)  # December untouched
        self.clock.now = datetime(2026, 11, 20, tzinfo=timezone.utc)
        self.assertEqual((await self.store.status(self.account_id)).used, 0)

    async def test_a_refund_never_goes_below_zero(self) -> None:
        claim = await self.store.try_consume(self.account_id)
        await self.store.refund(claim)
        await self.store.refund(claim)
        self.assertEqual((await self.store.status(self.account_id)).used, 0)

    async def test_release_refunds_at_most_once(self) -> None:
        claim = await self.store.try_consume(self.account_id)
        await self.store.hold("run-1", claim)
        self.assertTrue(await self.store.release("run-1", refund=True))
        self.assertFalse(await self.store.release("run-1", refund=True))
        self.assertEqual((await self.store.status(self.account_id)).used, 0)

    async def test_release_without_refund_keeps_the_run_spent(self) -> None:
        claim = await self.store.try_consume(self.account_id)
        await self.store.hold("run-1", claim)
        self.assertFalse(await self.store.release("run-1", refund=False))
        self.assertFalse(await self.store.release("run-1", refund=True))
        self.assertEqual((await self.store.status(self.account_id)).used, 1)

    async def test_releasing_a_run_that_holds_nothing_is_a_no_op(self) -> None:
        self.assertFalse(await self.store.release("never-held", refund=True))

    async def test_concurrent_takes_never_exceed_the_limit(self) -> None:
        results = await asyncio.gather(*(self.store.try_consume(self.account_id) for _ in range(25)))
        self.assertEqual(sum(1 for claim in results if claim is not None), 10)
        self.assertEqual((await self.store.status(self.account_id)).used, 10)

    async def test_off_when_the_setting_is_zero_or_below(self) -> None:
        for limit in (0, -1):
            store = self._make(limit)
            self.assertFalse(store.enabled)
            self.assertIsNone(await store.try_consume(self.account_id))
            status = await store.status(self.account_id)
            self.assertEqual((status.enabled, status.limit, status.used, status.remaining), (False, 0, 0, 0))


class SqlAllowanceTests(_AllowanceBehaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = _settings(database_url="sqlite://")
        self.database = Database(self.settings)
        self.addAsyncCleanup(self.database.close)
        await self.database.create_all()
        self.accounts = SqlAccountDirectory(
            self.database, users=AlwaysPresentIdentityProviderUsers(self.settings)
        )
        self.account_id = (await self.accounts.resolve_account("sub-1", "a@b.test")).account_id
        self.clock = _Clock(datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
        self.store = self._make(10)

    def _make(self, limit: int) -> SqlAccountFreeRuns:
        return SqlAccountFreeRuns(
            _settings(database_url="sqlite://", free_runs_per_account_monthly=limit), self.database, clock=self.clock
        )

    async def test_concurrent_takes_never_exceed_the_limit(self) -> None:
        # The suite's in-memory SQLite is one shared connection, which cannot
        # run transactions side by side. A file database with a connection
        # per request can: every take is its own transaction racing the rest.
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        with tempfile.TemporaryDirectory() as tmp:
            url = f"sqlite+aiosqlite:///{Path(tmp, 'race.sqlite3').as_posix()}"
            database = Database(_settings(database_url=url))
            database._engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 30})
            try:
                await database.create_all()
                account_id = (
                    await SqlAccountDirectory(
                        database, users=AlwaysPresentIdentityProviderUsers(self.settings)
                    ).resolve_account("sub-race")
                ).account_id
                store = SqlAccountFreeRuns(_settings(database_url=url), database, clock=self.clock)
                results = await asyncio.gather(*(store.try_consume(account_id) for _ in range(25)))
                self.assertEqual(sum(1 for claim in results if claim is not None), 10)
                self.assertEqual((await store.status(account_id)).used, 10)
            finally:
                await database.close()

    async def test_stale_holds_are_pruned_on_the_next_hold(self) -> None:
        claim = await self.store.try_consume(self.account_id)
        await self.store.hold("old-run", claim)
        self.clock.now += timedelta(days=3)
        await self.store.hold("new-run", claim)
        async with self.database.connect() as conn:
            run_ids = set((await conn.execute(select(account_free_run_holds.c.run_id))).scalars())
        self.assertEqual(run_ids, {"new-run"})

    async def test_account_deletion_removes_usage_and_holds(self) -> None:
        other = (await self.accounts.resolve_account("sub-2", "c@d.test")).account_id
        claim = await self.store.try_consume(self.account_id)
        await self.store.hold("run-1", claim)
        await self.store.try_consume(other)

        deleter = SqlAccountDeleter(self.settings, self.database)
        self.assertTrue(await deleter.delete_account("sub-1"))

        async with self.database.connect() as conn:
            mine = await conn.scalar(
                select(func.count()).select_from(account_free_runs).where(account_free_runs.c.account_id == self.account_id)
            )
            holds = await conn.scalar(select(func.count()).select_from(account_free_run_holds))
            theirs = await conn.scalar(
                select(account_free_runs.c.used).where(account_free_runs.c.account_id == other)
            )
        self.assertEqual((mine, holds, theirs), (0, 0, 1))


class InMemoryAllowanceTests(_AllowanceBehaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.accounts = InMemoryAccountDirectory()
        self.account_id = (await self.accounts.resolve_account("sub-1", "a@b.test")).account_id
        self.clock = _Clock(datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
        self.store = self._make(10)

    def _make(self, limit: int) -> InMemoryAccountFreeRuns:
        return InMemoryAccountFreeRuns(_settings(free_runs_per_account_monthly=limit), clock=self.clock)

    async def test_disabled_with_the_account_store(self) -> None:
        store = InMemoryAccountFreeRuns(_settings(), enabled=False)
        self.assertFalse(store.enabled)

    async def test_account_deletion_removes_usage_and_holds(self) -> None:
        other = (await self.accounts.resolve_account("sub-2", "c@d.test")).account_id
        claim = await self.store.try_consume(self.account_id)
        await self.store.hold("run-1", claim)
        await self.store.try_consume(other)
        deleter = InMemoryAccountDeleter(
            _settings(), accounts=self.accounts, api_keys=InMemoryApiKeyRepository(), free_runs=self.store
        )

        self.assertTrue(await deleter.delete_account("sub-1"))

        self.assertEqual((await self.store.status(self.account_id)).used, 0)
        self.assertFalse(await self.store.release("run-1", refund=True))
        self.assertEqual((await self.store.status(other)).used, 1)


class AlembicAccountFreeRunsTests(unittest.TestCase):
    def test_upgrade_creates_both_tables_and_downgrade_to_0002_removes_only_them(self) -> None:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "migrate.sqlite3").as_posix()
            config = Config(str(BACKEND / "alembic.ini"))
            config.set_main_option("script_location", str(BACKEND / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
            config.attributes["configure_logger"] = False

            with mock.patch.dict(os.environ, {"DATABASE_URL": ""}):
                command.upgrade(config, "head")
                engine = create_engine(f"sqlite:///{path}")
                try:
                    inspector = inspect(engine)
                    self.assertTrue({"account_free_runs", "account_free_run_holds"} <= set(inspector.get_table_names()))
                    self.assertEqual(
                        set(inspector.get_pk_constraint("account_free_runs")["constrained_columns"]),
                        {"account_id", "period"},
                    )
                    fks = inspector.get_foreign_keys("account_free_runs")
                    self.assertEqual(fks[0]["referred_table"], "accounts")
                    self.assertEqual(fks[0]["options"].get("ondelete"), "CASCADE")
                    command.downgrade(config, "0002_auth_user_deleter")
                    tables = set(inspect(engine).get_table_names())
                    self.assertFalse({"account_free_runs", "account_free_run_holds"} & tables)
                    self.assertIn("accounts", tables)
                finally:
                    engine.dispose()


def _load_migration():
    path = BACKEND / "migrations" / "versions" / "0003_account_free_runs.py"
    spec = importlib.util.spec_from_file_location("migration_0003_account_free_runs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PostgresMigrationPathTests(unittest.TestCase):
    """0003's Postgres branch with Alembic mocked (no Postgres in the suite)."""

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

    def _role_exists(self, exists: bool) -> None:
        self.op.get_bind.return_value.execute.return_value.scalar.return_value = 1 if exists else None

    def _ddl(self) -> str:
        return "\n".join(str(call.args[0]) for call in self.op.execute.call_args_list)

    def test_a_missing_role_fails_before_any_table_is_created(self) -> None:
        self._role_exists(False)
        with self.assertRaises(RuntimeError):
            self.migration.upgrade()
        self.op.create_table.assert_not_called()

    def test_rls_grants_and_policies_on_both_tables(self) -> None:
        self._role_exists(True)
        self.migration.upgrade()
        ddl = self._ddl()
        for table in ("account_free_runs", "account_free_run_holds"):
            self.assertIn(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY", ddl)
            self.assertIn(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO videolens_api", ddl)
            self.assertIn(f"CREATE POLICY videolens_api_all ON public.{table}", ddl)

    def test_offline_rendering_skips_the_role_check(self) -> None:
        self.context.is_offline_mode.return_value = True
        self.migration.upgrade()
        self.op.get_bind.return_value.execute.assert_not_called()
        self.assertIn("CREATE POLICY", self._ddl())

    def test_rejects_a_role_name_that_is_not_a_plain_identifier(self) -> None:
        with mock.patch.dict(os.environ, {"DATABASE_APP_ROLE": "x; DROP TABLE accounts"}):
            with self.assertRaises(ValueError):
                self.migration.upgrade()


if __name__ == "__main__":
    unittest.main()
