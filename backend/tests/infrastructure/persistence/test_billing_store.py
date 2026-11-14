"""The BillingAccounts and ExtraRunLedger adapters (docs/backend/billing.md):
SQL (SQLite through aiosqlite, standing in for Postgres) and in-memory
share one behaviour suite. Also: account deletion clears both, and
migration 0004 (SQLite round trip, Postgres branch with Alembic mocked)."""

import importlib.util
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy import inspect

from app.domain.entities import SubscriptionSnapshot
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_deleter import InMemoryAccountDeleter, SqlAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory, SqlAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
from app.infrastructure.persistence.billing_store import (
    DUE,
    HELD,
    InMemoryBillingAccounts,
    InMemoryExtraRunLedger,
    SqlBillingAccounts,
    SqlExtraRunLedger,
)
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.identity_users import AlwaysPresentIdentityProviderUsers

BACKEND = Path(__file__).resolve().parents[3]


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, gemini_api_key="k", **overrides)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _snapshot(status="active", sub="sub_1", customer="cus_1", end=None) -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        subscription_id=sub,
        customer_id=customer,
        status=status,
        price_id="price_m",
        interval="month",
        current_period_end=end or datetime(2026, 12, 13, tzinfo=timezone.utc),
        cancel_at_period_end=False,
    )


class _Behaviour:
    """Mixed into a TestCase whose asyncSetUp sets clock, accounts (the
    billing store), ledger, account_id and other_id."""

    async def test_link_is_idempotent_and_never_shared(self) -> None:
        first = await self.accounts.link_customer(self.account_id, "cus_1")
        again = await self.accounts.link_customer(self.account_id, "cus_1")
        self.assertEqual((first.stripe_customer_id, again.stripe_customer_id), ("cus_1", "cus_1"))
        self.assertEqual((await self.accounts.by_customer("cus_1")).account_id, self.account_id)
        with self.assertRaises(RuntimeError):
            await self.accounts.link_customer(self.other_id, "cus_1")
        self.assertIsNone(await self.accounts.get(self.other_id))

    async def test_apply_subscription(self) -> None:
        self.assertFalse(await self.accounts.apply_subscription(self.account_id, _snapshot()))  # no link yet
        await self.accounts.link_customer(self.account_id, "cus_1")
        self.assertTrue(await self.accounts.apply_subscription(self.account_id, _snapshot()))
        row = await self.accounts.get(self.account_id)
        self.assertEqual((row.stripe_subscription_id, row.status, row.interval), ("sub_1", "active", "month"))
        self.assertEqual(row.current_period_end, datetime(2026, 12, 13, tzinfo=timezone.utc))
        self.assertTrue(await self.accounts.apply_subscription(self.account_id, _snapshot("past_due")))
        self.assertEqual((await self.accounts.get(self.account_id)).status, "past_due")

    async def test_an_ended_subscription_never_replaces_a_live_one(self) -> None:
        await self.accounts.link_customer(self.account_id, "cus_1")
        await self.accounts.apply_subscription(self.account_id, _snapshot(sub="sub_new"))
        self.assertFalse(await self.accounts.apply_subscription(self.account_id, _snapshot("canceled", sub="sub_old")))
        self.assertEqual((await self.accounts.get(self.account_id)).stripe_subscription_id, "sub_new")
        # But a new live one replaces an ended one.
        await self.accounts.apply_subscription(self.account_id, _snapshot("canceled", sub="sub_new"))
        self.assertTrue(await self.accounts.apply_subscription(self.account_id, _snapshot(sub="sub_3")))

    async def test_events(self) -> None:
        self.assertFalse(await self.accounts.event_seen("evt_1"))
        await self.accounts.mark_event("evt_1", "invoice.paid")
        await self.accounts.mark_event("evt_1", "invoice.paid")
        self.assertTrue(await self.accounts.event_seen("evt_1"))

    async def test_ledger_held_due_reported_exactly_once(self) -> None:
        await self.ledger.hold("run-1", account_id=self.account_id, customer_id="cus_1", period="2026-11")
        self.assertEqual(await self.ledger.count(self.account_id, "2026-11"), 1)
        charge = await self.ledger.complete("run-1")
        self.assertEqual((charge.run_id, charge.stripe_customer_id), ("run-1", "cus_1"))
        self.assertIsNone(await self.ledger.complete("run-1"))
        self.assertFalse(await self.ledger.void("run-1"))
        self.assertEqual([c.run_id for c in await self.ledger.due()], ["run-1"])
        await self.ledger.mark_reported("run-1")
        self.assertEqual(await self.ledger.due(), [])
        self.assertEqual(await self.ledger.count(self.account_id, "2026-11"), 1)

    async def test_ledger_void_wins_once_and_is_never_billed(self) -> None:
        await self.ledger.hold("run-2", account_id=self.account_id, customer_id="cus_1", period="2026-11")
        self.assertTrue(await self.ledger.void("run-2"))
        self.assertFalse(await self.ledger.void("run-2"))
        self.assertIsNone(await self.ledger.complete("run-2"))
        self.assertEqual(await self.ledger.due(), [])
        # A voided run does not count toward the cap.
        self.assertEqual(await self.ledger.count(self.account_id, "2026-11"), 0)

    async def test_unknown_runs_are_not_extra_runs(self) -> None:
        self.assertIsNone(await self.ledger.complete("plain-run"))
        self.assertFalse(await self.ledger.void("plain-run"))

    async def test_count_is_per_period(self) -> None:
        await self.ledger.hold("a", account_id=self.account_id, customer_id="cus_1", period="2026-10")
        await self.ledger.hold("b", account_id=self.account_id, customer_id="cus_1", period="2026-11")
        self.assertEqual(await self.ledger.count(self.account_id, "2026-11"), 1)
        self.assertEqual(await self.ledger.count(self.other_id, "2026-11"), 0)


class SqlBillingStoreTests(_Behaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = _settings(database_url="sqlite://")
        self.database = Database(self.settings)
        self.addAsyncCleanup(self.database.close)
        await self.database.create_all()
        directory = SqlAccountDirectory(self.database, users=AlwaysPresentIdentityProviderUsers(self.settings))
        self.account_id = (await directory.resolve_account("sub-1", "a@b.test")).account_id
        self.other_id = (await directory.resolve_account("sub-2", "c@d.test")).account_id
        self.clock = _Clock(datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
        self.accounts = SqlBillingAccounts(self.settings, self.database, clock=self.clock)
        self.ledger = SqlExtraRunLedger(self.settings, self.database, clock=self.clock)

    async def test_stale_holds_are_voided_on_the_next_hold(self) -> None:
        await self.ledger.hold("old", account_id=self.account_id, customer_id="cus_1", period="2026-11")
        self.clock.now += timedelta(days=3)
        await self.ledger.hold("new", account_id=self.account_id, customer_id="cus_1", period="2026-11")
        self.assertIsNone(await self.ledger.complete("old"))
        self.assertIsNotNone(await self.ledger.complete("new"))

    async def test_deleting_the_account_removes_its_billing_rows(self) -> None:
        await self.accounts.link_customer(self.account_id, "cus_1")
        await self.ledger.hold("run-1", account_id=self.account_id, customer_id="cus_1", period="2026-11")
        deleter = SqlAccountDeleter(self.settings, self.database)
        self.assertTrue(await deleter.delete_account("sub-1"))
        self.assertIsNone(await self.accounts.get(self.account_id))
        self.assertEqual(await self.ledger.count(self.account_id, "2026-11"), 0)


class InMemoryBillingStoreTests(_Behaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = _settings()
        self.clock = _Clock(datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
        self.account_id, self.other_id = "acct-1", "acct-2"
        self.accounts = InMemoryBillingAccounts(self.settings, clock=self.clock)
        self.ledger = InMemoryExtraRunLedger(self.settings, clock=self.clock)

    async def test_deleting_the_account_forgets_it(self) -> None:
        directory = InMemoryAccountDirectory()
        account = await directory.resolve_account("sub-1", "a@b.test")
        await self.accounts.link_customer(account.account_id, "cus_1")
        await self.ledger.hold("run-1", account_id=account.account_id, customer_id="cus_1", period="2026-11")
        deleter = InMemoryAccountDeleter(
            self.settings,
            accounts=directory,
            api_keys=InMemoryApiKeyRepository(),
            billing_accounts=self.accounts,
            extra_runs=self.ledger,
        )
        await deleter.delete_account("sub-1")
        self.assertIsNone(await self.accounts.get(account.account_id))
        self.assertIsNone(self.ledger.state("run-1"))

    def test_states_are_the_documented_names(self) -> None:
        self.assertEqual((HELD, DUE), ("held", "due"))


class AlembicBillingTests(unittest.TestCase):
    def test_upgrade_and_downgrade_on_sqlite(self) -> None:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "migrate.sqlite3").as_posix()
            config = Config(str(BACKEND / "alembic.ini"))
            config.set_main_option("script_location", str(BACKEND / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
            config.attributes["configure_logger"] = False
            tables = {"billing_accounts", "billing_events", "billing_extra_runs"}

            with mock.patch.dict(os.environ, {"DATABASE_URL": ""}):
                command.upgrade(config, "head")
                engine = create_engine(f"sqlite:///{path}")
                try:
                    inspector = inspect(engine)
                    self.assertTrue(tables <= set(inspector.get_table_names()))
                    for table in ("billing_accounts", "billing_extra_runs"):
                        fk = inspector.get_foreign_keys(table)[0]
                        self.assertEqual((fk["referred_table"], fk["options"].get("ondelete")), ("accounts", "CASCADE"))
                    indexes = {index["name"] for index in inspector.get_indexes("billing_extra_runs")}
                    self.assertEqual(indexes, {"ix_billing_extra_runs_account_period", "ix_billing_extra_runs_state"})
                    command.downgrade(config, "0003_account_free_runs")
                    remaining = set(inspect(engine).get_table_names())
                    self.assertFalse(tables & remaining)
                    self.assertIn("account_free_runs", remaining)
                finally:
                    engine.dispose()


def _load_migration():
    path = BACKEND / "migrations" / "versions" / "0004_billing.py"
    spec = importlib.util.spec_from_file_location("migration_0004_billing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PostgresMigrationPathTests(unittest.TestCase):
    """0004's Postgres branch with Alembic mocked (no Postgres in the suite)."""

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

    def test_rls_grants_and_policies_on_all_three_tables(self) -> None:
        self._role_exists(True)
        self.migration.upgrade()
        ddl = self._ddl()
        for table in ("billing_accounts", "billing_events", "billing_extra_runs"):
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
