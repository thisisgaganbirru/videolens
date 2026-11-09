"""The identity adapters: SQL (SQLite through aiosqlite, standing in for
Postgres) and the in-memory ones a deployment without `DATABASE_URL` uses.
Both run the same behaviour suite, so their rules cannot drift apart."""

import os
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from sqlalchemy import inspect, select

from app.domain.errors import ApiKeyLimitError
from app.infrastructure.config import Settings
from app.infrastructure.persistence import api_key_repository as key_module
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory, SqlAccountDirectory
from app.infrastructure.persistence.api_key_repository import (
    InMemoryApiKeyRepository,
    SqlApiKeyRepository,
    hash_secret,
)
from app.infrastructure.persistence.database import Database, normalize_database_url, utcnow
from app.infrastructure.persistence.schema import api_keys

BACKEND = Path(__file__).resolve().parents[3]
SECRET_SHAPE = re.compile(r"^vl_live_[A-Za-z0-9_-]{43}$")


class NormalizeUrlTests(unittest.TestCase):
    def test_provider_forms_become_async_driver_urls(self) -> None:
        self.assertEqual(normalize_database_url(""), "")
        self.assertEqual(normalize_database_url("  "), "")
        self.assertEqual(normalize_database_url("postgres://u:p@h:6543/db"), "postgresql+asyncpg://u:p@h:6543/db")
        self.assertEqual(normalize_database_url("postgresql://u:p@h/db"), "postgresql+asyncpg://u:p@h/db")
        self.assertEqual(normalize_database_url("sqlite:///x.db"), "sqlite+aiosqlite:///x.db")
        self.assertEqual(normalize_database_url("sqlite+aiosqlite:///x.db"), "sqlite+aiosqlite:///x.db")

    def test_blank_url_disables_the_database_without_connecting(self) -> None:
        database = Database(Settings(_env_file=None, gemini_api_key="k", database_url=""))
        self.assertFalse(database.enabled)
        with self.assertRaises(RuntimeError):
            database.engine()


class HiddenParameterTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_error_text_omits_bound_values(self) -> None:
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        database = Database(Settings(_env_file=None, gemini_api_key="k", database_url="sqlite://"))
        self.addAsyncCleanup(database.close)
        with self.assertRaises(DBAPIError) as caught:
            async with database.connect() as conn:
                await conn.execute(text("SELECT * FROM no_such_table WHERE email = :email"), {"email": "person@example.com"})

        message = str(caught.exception)
        self.assertNotIn("person@example.com", message)
        self.assertIn("hidden", message)


class _IdentityBehaviour:
    """Mixed into a TestCase whose asyncSetUp sets self.accounts and self.keys."""

    async def test_first_sign_in_creates_account_personal_workspace_and_ownership(self) -> None:
        account = await self.accounts.resolve_account("sub-1", "a@b.test")

        self.assertEqual(account.external_id, "sub-1")
        self.assertEqual(account.email, "a@b.test")
        workspace = await self.accounts.get_workspace(account.default_workspace_id)
        self.assertEqual(workspace.name, "Personal")
        self.assertEqual(workspace.owner_account_id, account.account_id)
        self.assertEqual(await self.accounts.member_role(workspace.workspace_id, account.account_id), "owner")
        self.assertIsNone(await self.accounts.member_role(workspace.workspace_id, "someone-else"))
        self.assertIsNone(await self.accounts.get_workspace("no-such-workspace"))

    async def test_later_sign_ins_reuse_the_account_and_keep_email_current(self) -> None:
        first = await self.accounts.resolve_account("sub-1", "a@b.test")
        same = await self.accounts.resolve_account("sub-1")
        changed = await self.accounts.resolve_account("sub-1", "new@b.test")

        self.assertEqual(same.account_id, first.account_id)
        self.assertEqual(same.default_workspace_id, first.default_workspace_id)
        self.assertEqual(same.email, "a@b.test")
        self.assertEqual(changed.email, "new@b.test")
        other = await self.accounts.resolve_account("sub-2")
        self.assertNotEqual(other.account_id, first.account_id)

    async def _workspace(self) -> str:
        return (await self.accounts.resolve_account("sub-1")).default_workspace_id

    async def test_issue_returns_the_secret_once_with_a_recognisable_prefix(self) -> None:
        workspace_id = await self._workspace()

        created = await self.keys.issue(workspace_id, "ci", ["runs:read"], max_active=10)

        self.assertRegex(created.secret, SECRET_SHAPE)
        self.assertEqual(created.key.prefix, created.secret[: len("vl_live_") + 8])
        self.assertEqual(created.key.scopes, ["runs:read"])
        self.assertTrue(created.key.active)
        listed = await self.keys.list_for_workspace(workspace_id)
        self.assertEqual([key.key_id for key in listed], [created.key.key_id])
        self.assertFalse(hasattr(listed[0], "secret"))

    async def test_authenticate_finds_live_keys_only(self) -> None:
        workspace_id = await self._workspace()
        created = await self.keys.issue(workspace_id, "ci", ["runs:read"], max_active=10)

        found = await self.keys.authenticate(created.secret)
        self.assertEqual(found.key_id, created.key.key_id)
        self.assertIsNone(await self.keys.authenticate("vl_live_wrong"))
        self.assertIsNone(await self.keys.authenticate("eyJ.not.a.key"))
        self.assertIsNone(await self.keys.authenticate(created.secret + "x"))

        self.assertTrue(await self.keys.revoke(workspace_id, created.key.key_id))
        self.assertFalse(await self.keys.revoke(workspace_id, created.key.key_id))
        self.assertIsNone(await self.keys.authenticate(created.secret))
        revoked = (await self.keys.list_for_workspace(workspace_id))[0]
        self.assertFalse(revoked.active)
        self.assertIsNotNone(revoked.revoked_at)

    async def test_revoke_is_scoped_to_the_workspace(self) -> None:
        mine = await self._workspace()
        theirs = (await self.accounts.resolve_account("sub-2")).default_workspace_id
        created = await self.keys.issue(theirs, "theirs", ["runs:read"], max_active=10)

        self.assertFalse(await self.keys.revoke(mine, created.key.key_id))
        self.assertIsNotNone(await self.keys.authenticate(created.secret))

    async def test_cap_counts_active_keys_per_workspace(self) -> None:
        workspace_id = await self._workspace()
        other = (await self.accounts.resolve_account("sub-2")).default_workspace_id
        first = await self.keys.issue(workspace_id, "a", [], max_active=2)
        await self.keys.issue(workspace_id, "b", [], max_active=2)

        with self.assertRaises(ApiKeyLimitError) as caught:
            await self.keys.issue(workspace_id, "c", [], max_active=2)
        self.assertIn("at most 2", str(caught.exception))
        await self.keys.issue(other, "elsewhere", [], max_active=2)

        await self.keys.revoke(workspace_id, first.key.key_id)
        await self.keys.issue(workspace_id, "c", [], max_active=2)

    async def test_last_used_is_written_at_most_once_a_minute(self) -> None:
        workspace_id = await self._workspace()
        created = await self.keys.issue(workspace_id, "ci", [], max_active=10)
        start = utcnow()

        with mock.patch.object(key_module, "utcnow", return_value=start):
            first = await self.keys.authenticate(created.secret)
        with mock.patch.object(key_module, "utcnow", return_value=start + timedelta(seconds=30)):
            soon = await self.keys.authenticate(created.secret)
        with mock.patch.object(key_module, "utcnow", return_value=start + timedelta(seconds=61)):
            later = await self.keys.authenticate(created.secret)

        self.assertEqual(first.last_used_at, start)
        self.assertEqual(soon.last_used_at, start)
        self.assertEqual(later.last_used_at, start + timedelta(seconds=61))


class SqlAdapterTests(_IdentityBehaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database(Settings(_env_file=None, gemini_api_key="k", database_url="sqlite://"))
        await self.database.create_all()
        self.accounts = SqlAccountDirectory(self.database)
        self.keys = SqlApiKeyRepository(self.database)

    async def asyncTearDown(self) -> None:
        await self.database.close()

    async def test_only_the_hash_is_stored(self) -> None:
        workspace_id = await self._workspace()
        created = await self.keys.issue(workspace_id, "ci", [], max_active=10)

        async with self.database.connect() as conn:
            row = (await conn.execute(select(api_keys))).one()
        self.assertEqual(row.key_hash, hash_secret(created.secret))
        self.assertNotIn(created.secret, [str(value) for value in row])

    async def test_ping(self) -> None:
        self.assertTrue(await self.accounts.ping())


class InMemoryAdapterTests(_IdentityBehaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.accounts = InMemoryAccountDirectory()
        self.keys = InMemoryApiKeyRepository()

    async def test_disabled_store_knows_nothing_and_issues_nothing(self) -> None:
        accounts = InMemoryAccountDirectory(enabled=False)
        keys = InMemoryApiKeyRepository(enabled=False)

        self.assertFalse(accounts.enabled)
        with self.assertRaises(RuntimeError):
            await keys.issue("ws", "x", [], max_active=10)
        self.assertIsNone(await keys.authenticate("vl_live_anything"))


class AlembicMigrationTests(unittest.TestCase):
    def test_upgrade_creates_the_four_tables_and_downgrade_removes_them(self) -> None:
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
                    tables = set(inspect(engine).get_table_names())
                    self.assertTrue({"accounts", "workspaces", "workspace_members", "api_keys"} <= tables)
                    command.downgrade(config, "base")
                    tables = set(inspect(engine).get_table_names())
                    self.assertFalse({"accounts", "workspaces", "workspace_members", "api_keys"} & tables)
                finally:
                    engine.dispose()


def _load_identity_migration():
    import importlib.util

    path = BACKEND / "migrations" / "versions" / "0001_identity.py"
    spec = importlib.util.spec_from_file_location("migration_0001_identity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PostgresMigrationPathTests(unittest.TestCase):
    """The Postgres-only branch of `0001_identity`, with Alembic's `op` and
    `context` mocked: no Postgres is available to the suite. Pins that a
    missing backend role fails the migration before any DDL (a NOTICE was
    silently dropped by asyncpg), and that a missing `auth.users` grant is
    reported loudly without failing."""

    def setUp(self) -> None:
        self.migration = _load_identity_migration()
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

    def _answers(self, *, role: bool, auth_users: bool = True, delete_granted: bool = True) -> None:
        def execute(statement, params=None):
            sql = str(statement)
            result = mock.MagicMock()
            if "pg_roles" in sql:
                result.scalar.return_value = 1 if role else None
            elif "to_regclass" in sql:
                result.scalar.return_value = "auth.users" if auth_users else None
            elif "has_table_privilege" in sql:
                result.scalar.return_value = delete_granted
            return result

        self.op.get_bind.return_value.execute.side_effect = execute

    def _ddl(self) -> str:
        return "\n".join(str(call.args[0]) for call in self.op.execute.call_args_list)

    def test_a_missing_role_fails_before_any_table_is_created(self) -> None:
        self._answers(role=False)
        with self.assertRaises(RuntimeError) as caught:
            self.migration.upgrade()
        self.assertIn("DATABASE_APP_ROLE", str(caught.exception))
        self.assertIn("videolens_api", str(caught.exception))
        self.op.create_table.assert_not_called()
        self.op.execute.assert_not_called()

    def test_with_the_role_present_grants_rls_and_policies_are_applied(self) -> None:
        self._answers(role=True)
        self.migration.upgrade()
        ddl = self._ddl()
        self.assertIn("GRANT USAGE ON SCHEMA public TO videolens_api", ddl)
        for table in ("accounts", "workspaces", "workspace_members", "api_keys"):
            self.assertIn(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY", ddl)
            self.assertIn(f"ON public.{table} TO videolens_api", ddl)
            self.assertIn(f"CREATE POLICY videolens_api_all ON public.{table}", ddl)

    def test_a_missing_auth_users_grant_warns_but_does_not_fail(self) -> None:
        self._answers(role=True, delete_granted=False)
        with self.assertLogs("alembic.migration.identity", level="WARNING") as logs:
            self.migration.upgrade()
        self.assertIn("auth.users", " ".join(logs.output))
        self.context.config.print_stdout.assert_called()

    def test_a_granted_auth_users_delete_is_quiet(self) -> None:
        self._answers(role=True, delete_granted=True)
        with self.assertNoLogs("alembic.migration.identity", level="WARNING"):
            self.migration.upgrade()

    def test_offline_rendering_skips_the_live_checks(self) -> None:
        self.context.is_offline_mode.return_value = True
        self.migration.upgrade()
        self.op.get_bind.return_value.execute.assert_not_called()
        self.assertIn("CREATE POLICY", self._ddl())

    def test_the_role_name_must_be_a_plain_identifier(self) -> None:
        with mock.patch.dict(os.environ, {"DATABASE_APP_ROLE": "x; DROP TABLE accounts"}):
            with self.assertRaises(ValueError):
                self.migration.upgrade()
        self.op.create_table.assert_not_called()


if __name__ == "__main__":
    unittest.main()
