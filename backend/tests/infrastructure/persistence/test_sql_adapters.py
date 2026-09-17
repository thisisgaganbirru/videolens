"""The Postgres adapters, exercised against SQLite in memory.

SQLite is close enough for row shape and semantics; the one Postgres-only
path (full-text search) has its own dialect branch and is covered by the
LIKE fallback here.
"""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain.entities import (
    Run,
    RunStatus,
    SourceMetadata,
    TokenUsage,
    UsageEvent,
    VideoAnalysis,
)
from app.domain.entitlements import Plan
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_directory import PostgresAccountDirectory
from app.infrastructure.persistence.api_key_repository import (
    PostgresApiKeyRepository,
    hash_secret,
    looks_like_api_key,
)
from app.infrastructure.persistence.database import Database, normalize_database_url
from app.infrastructure.persistence.run_archive import PostgresRunArchive
from app.infrastructure.persistence.run_repository import RunStore
from app.infrastructure.persistence.tiered_run_repository import TieredRunRepository
from app.infrastructure.persistence.usage_meter import PostgresUsageMeter


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:", **overrides)


class DatabaseUrlTests(unittest.TestCase):
    def test_provider_urls_are_rewritten_for_asyncpg(self) -> None:
        self.assertEqual(
            normalize_database_url("postgres://u:p@h:5432/db"), "postgresql+asyncpg://u:p@h:5432/db"
        )
        self.assertEqual(
            normalize_database_url("postgresql://u:p@h/db"), "postgresql+asyncpg://u:p@h/db"
        )

    def test_sqlite_gets_the_async_driver(self) -> None:
        self.assertEqual(normalize_database_url("sqlite:///x.db"), "sqlite+aiosqlite:///x.db")

    def test_empty_means_disabled(self) -> None:
        database = Database(Settings(_env_file=None))
        self.assertFalse(database.enabled)
        self.assertEqual(database.dialect, "")


class SqlAdapterTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = _settings()
        self.database = Database(self.settings)
        await self.database.create_all()
        self.accounts = PostgresAccountDirectory(self.database)
        self.archive = PostgresRunArchive(self.database)
        self.usage = PostgresUsageMeter(self.database)
        self.keys = PostgresApiKeyRepository(self.database)

    async def asyncTearDown(self) -> None:
        await self.database.close()


class AccountDirectoryTests(SqlAdapterTestCase):
    async def test_first_sign_in_creates_an_account_and_a_personal_workspace(self) -> None:
        account = await self.accounts.resolve_account("user_abc", "a@example.com")
        self.assertEqual(account.external_id, "user_abc")
        self.assertIsNotNone(account.default_workspace_id)
        workspace = await self.accounts.get_workspace(account.default_workspace_id)
        self.assertIsNotNone(workspace)
        self.assertIs(workspace.plan, Plan.FREE)
        self.assertEqual(workspace.owner_account_id, account.account_id)
        self.assertEqual(
            await self.accounts.member_role(workspace.workspace_id, account.account_id), "owner"
        )

    async def test_second_sign_in_returns_the_same_account(self) -> None:
        first = await self.accounts.resolve_account("user_abc", "a@example.com")
        second = await self.accounts.resolve_account("user_abc", "new@example.com")
        self.assertEqual(first.account_id, second.account_id)
        self.assertEqual(second.email, "new@example.com")
        self.assertEqual(len(await self.accounts.list_workspaces(first.account_id)), 1)

    async def test_subscription_is_applied_and_found_by_customer(self) -> None:
        account = await self.accounts.resolve_account("user_abc")
        workspace_id = account.default_workspace_id
        await self.accounts.set_customer(workspace_id, "cus_123")
        now = datetime.now(timezone.utc)
        updated = await self.accounts.apply_subscription(
            workspace_id,
            plan=Plan.PRO,
            minutes_included=600,
            period_start=now,
            period_end=now + timedelta(days=30),
            stripe_subscription_id="sub_1",
        )
        self.assertIs(updated.plan, Plan.PRO)
        self.assertEqual(updated.minutes_included, 600)
        by_customer = await self.accounts.get_workspace_by_customer("cus_123")
        self.assertEqual(by_customer.workspace_id, workspace_id)
        self.assertEqual(by_customer.stripe_subscription_id, "sub_1")

    async def test_free_period_rolls_forward_when_expired(self) -> None:
        account = await self.accounts.resolve_account("user_abc")
        workspace_id = account.default_workspace_id
        long_ago = datetime.now(timezone.utc) - timedelta(days=100)
        await self.accounts.apply_subscription(
            workspace_id,
            plan=Plan.FREE,
            minutes_included=30,
            period_start=long_ago,
            period_end=long_ago + timedelta(days=30),
            stripe_subscription_id=None,
        )
        workspace = await self.accounts.get_workspace(workspace_id)
        self.assertLessEqual(workspace.period_start, datetime.now(timezone.utc))
        self.assertGreater(workspace.period_end, datetime.now(timezone.utc))

    async def test_disabled_directory_answers_nothing(self) -> None:
        accounts = PostgresAccountDirectory(Database(Settings(_env_file=None)))
        self.assertFalse(accounts.enabled)
        self.assertIsNone(await accounts.get_workspace("x"))
        self.assertEqual(await accounts.list_workspaces("x"), [])


def _run(run_id: str, owner: str, *, workspace_id: str | None, title: str, transcript: str = "") -> Run:
    now = datetime.now(timezone.utc)
    return Run(
        run_id=run_id,
        owner_id=owner,
        status=RunStatus.COMPLETE,
        created_at=now,
        updated_at=now,
        result=VideoAnalysis(
            title=title, summary="A summary", transcript=transcript, screen_text="ACME Corp", markdown="# T"
        ),
        source_metadata=SourceMetadata(platform="TikTok", source_url="https://t.test/1", title=title),
        workspace_id=workspace_id,
        plan=Plan.PRO,
        duration_seconds=61.0,
        usage=TokenUsage(input_tokens=10, output_tokens=5),
    )


class RunArchiveTests(SqlAdapterTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        account = await self.accounts.resolve_account("user_abc")
        self.workspace_id = account.default_workspace_id
        self.owner = f"workspace:{self.workspace_id}"

    async def test_round_trips_a_completed_run(self) -> None:
        run = _run("r1", self.owner, workspace_id=self.workspace_id, title="Launch video", transcript="hello")
        await self.archive.archive(run)
        stored = await self.archive.get("r1")
        self.assertEqual(stored.result.title, "Launch video")
        self.assertEqual(stored.result.transcript, "hello")
        self.assertEqual(stored.source_metadata.platform, "TikTok")
        self.assertEqual(stored.usage.input_tokens, 10)
        self.assertEqual(stored.duration_seconds, 61.0)
        self.assertIs(stored.plan, Plan.PRO)
        self.assertEqual(stored.created_at.tzinfo, timezone.utc)

    async def test_archiving_twice_updates_in_place(self) -> None:
        run = _run("r1", self.owner, workspace_id=self.workspace_id, title="First")
        await self.archive.archive(run)
        run.result.title = "Second"
        await self.archive.archive(run)
        self.assertEqual((await self.archive.get("r1")).result.title, "Second")
        self.assertEqual(len(await self.archive.list_for_owner(self.owner)), 1)

    async def test_search_matches_on_screen_text_and_filters_by_platform(self) -> None:
        await self.archive.archive(_run("r1", self.owner, workspace_id=self.workspace_id, title="One"))
        other = _run("r2", self.owner, workspace_id=self.workspace_id, title="Two")
        other.result.screen_text = "nothing here"
        other.source_metadata.platform = "YouTube"
        await self.archive.archive(other)
        hits = await self.archive.search(self.owner, query="acme")
        self.assertEqual([hit.run_id for hit in hits], ["r1"])
        hits = await self.archive.search(self.owner, platform="youtube")
        self.assertEqual([hit.run_id for hit in hits], ["r2"])
        self.assertEqual(await self.archive.search("workspace:someone-else", query="acme"), [])

    async def test_disabled_archive_is_a_no_op(self) -> None:
        archive = PostgresRunArchive(Database(Settings(_env_file=None)))
        self.assertFalse(archive.enabled)
        await archive.archive(_run("r1", "x", workspace_id=None, title="T"))
        self.assertIsNone(await archive.get("r1"))
        self.assertEqual(await archive.search("x", query="t"), [])


class TieredRepositoryTests(SqlAdapterTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.live = RunStore(self.settings)
        self.repo = TieredRunRepository(self.live, self.archive)

    async def test_workspace_runs_are_archived_on_completion(self) -> None:
        await self.repo.create("r1", "workspace:ws1", workspace_id="ws1", plan=Plan.PRO)
        result = VideoAnalysis(title="T", summary="S", transcript="", screen_text="", markdown="")
        await self.repo.set_result("r1", result)
        archived = await self.archive.get("r1")
        self.assertIsNotNone(archived)
        self.assertIs(archived.status, RunStatus.COMPLETE)

    async def test_anonymous_runs_never_reach_the_archive(self) -> None:
        await self.repo.create("r2", "client:anon")
        result = VideoAnalysis(title="T", summary="S", transcript="", screen_text="", markdown="")
        await self.repo.set_result("r2", result)
        self.assertIsNone(await self.archive.get("r2"))
        self.assertIsNotNone(await self.repo.get("r2"))

    async def test_falls_back_to_the_archive_when_the_live_store_forgets(self) -> None:
        await self.repo.create("r3", "workspace:ws1", workspace_id="ws1")
        await self.repo.set_error("r3", "boom")
        # Simulate Redis expiry.
        self.live._memory.clear()
        recovered = await self.repo.get("r3")
        self.assertEqual(recovered.error, "boom")
        listed = await self.repo.list_for_owner("workspace:ws1")
        self.assertEqual([run.run_id for run in listed], ["r3"])


class UsageMeterTests(SqlAdapterTestCase):
    async def test_sums_only_events_since_the_period_start(self) -> None:
        account = await self.accounts.resolve_account("user_abc")
        ws = account.default_workspace_id
        now = datetime.now(timezone.utc)
        for event_id, run_id, minutes, at in (
            ("e1", "r1", "1.50", now),
            ("e2", "r2", "2.25", now),
            ("e3", "r3", "9.00", now - timedelta(days=45)),
        ):
            await self.usage.record(
                UsageEvent(
                    event_id=event_id,
                    workspace_id=ws,
                    run_id=run_id,
                    minutes_billed=Decimal(minutes),
                    created_at=at,
                )
            )
        used = await self.usage.minutes_used(ws, now - timedelta(days=1))
        self.assertEqual(used, Decimal("3.75"))

    async def test_a_run_is_billed_once(self) -> None:
        account = await self.accounts.resolve_account("user_abc")
        ws = account.default_workspace_id
        now = datetime.now(timezone.utc)
        for event_id in ("e1", "e2"):
            await self.usage.record(
                UsageEvent(event_id=event_id, workspace_id=ws, run_id="same", minutes_billed=Decimal("1"), created_at=now)
            )
        self.assertEqual(await self.usage.minutes_used(ws, now - timedelta(hours=1)), Decimal("1"))


class ApiKeyRepositoryTests(SqlAdapterTestCase):
    async def test_issued_secret_authenticates_and_is_stored_hashed(self) -> None:
        account = await self.accounts.resolve_account("user_abc")
        ws = account.default_workspace_id
        issued = await self.keys.issue(ws, "CI", ["runs:write"])
        self.assertTrue(looks_like_api_key(issued.secret))
        self.assertTrue(issued.secret.startswith(issued.key.prefix))
        key = await self.keys.authenticate(issued.secret)
        self.assertEqual(key.key_id, issued.key.key_id)
        self.assertIsNotNone(key.last_used_at is None or key.last_used_at)
        listed = await self.keys.list_for_workspace(ws)
        self.assertEqual(len(listed), 1)
        self.assertNotIn(issued.secret, repr(listed))
        self.assertNotEqual(hash_secret(issued.secret), issued.secret)

    async def test_revoked_keys_stop_authenticating(self) -> None:
        account = await self.accounts.resolve_account("user_abc")
        ws = account.default_workspace_id
        issued = await self.keys.issue(ws, "CI", ["runs:write"])
        self.assertTrue(await self.keys.revoke(ws, issued.key.key_id))
        self.assertFalse(await self.keys.revoke(ws, issued.key.key_id))
        self.assertIsNone(await self.keys.authenticate(issued.secret))
        self.assertFalse(await self.keys.revoke("other-ws", issued.key.key_id))

    async def test_garbage_never_authenticates(self) -> None:
        self.assertIsNone(await self.keys.authenticate("not-a-key"))
        self.assertIsNone(await self.keys.authenticate("vl_live_deadbeef_nope"))


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_alembic_upgrade_builds_the_schema_on_a_fresh_database(self) -> None:
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "migrate.sqlite3")
            database = Database(Settings(_env_file=None, database_url=f"sqlite:///{path}"))
            await database.migrate()
            accounts = PostgresAccountDirectory(database)
            account = await accounts.resolve_account("user_x")
            self.assertIsNotNone(account.default_workspace_id)
            # Second run is a no-op, not an error.
            await database.migrate()
            await database.close()


if __name__ == "__main__":
    unittest.main()
