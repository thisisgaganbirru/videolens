"""The AccountDeleter adapters: SQL (SQLite standing in for Postgres) and
in-memory share one behaviour suite; the Postgres-only `auth.users` step and
migration `0002_auth_user_deleter` are pinned with mocks, since no Postgres
is available to the suite."""

import importlib.util
import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

from sqlalchemy import func, insert, select

from app.domain.errors import AuthenticationError
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_deleter import InMemoryAccountDeleter, SqlAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory, SqlAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository, SqlApiKeyRepository
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.identity_users import (
    AlwaysPresentIdentityProviderUsers,
    SqlIdentityProviderUsers,
)
from app.infrastructure.persistence.schema import accounts, api_keys, workspace_members, workspaces

BACKEND = Path(__file__).resolve().parents[3]


class _Users:
    """`IdentityProviderUsers` fake (the application fakes module is not
    importable from here under `unittest discover`)."""

    def __init__(self, gone: set[str] | None = None) -> None:
        self.gone = gone if gone is not None else set()
        self.asked: list[str] = []

    async def exists(self, external_id: str) -> bool:
        self.asked.append(external_id)
        return external_id not in self.gone


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, gemini_api_key="k", **overrides)


class _DeleterBehaviour:
    """Mixed into a TestCase whose asyncSetUp sets self.accounts, self.keys,
    self.deleter, and implements `_add_member(workspace_id, account_id)`."""

    async def _two_people(self):
        mine = await self.accounts.resolve_account("sub-1", "me@b.test")
        theirs = await self.accounts.resolve_account("sub-2", "them@b.test")
        my_key = await self.keys.issue(mine.default_workspace_id, "mine", [], max_active=10)
        their_key = await self.keys.issue(theirs.default_workspace_id, "theirs", [], max_active=10)
        # sub-1 is also a member of sub-2's workspace; that membership goes,
        # the workspace stays.
        await self._add_member(theirs.default_workspace_id, mine.account_id)
        return mine, theirs, my_key, their_key

    async def test_the_persons_rows_go_and_everyone_elses_stay(self) -> None:
        mine, theirs, my_key, their_key = await self._two_people()

        self.assertTrue(await self.deleter.delete_account("sub-1"))

        self.assertIsNone(await self.accounts.get_workspace(mine.default_workspace_id))
        self.assertIsNone(await self.keys.authenticate(my_key.secret))
        self.assertIsNone(await self.accounts.member_role(theirs.default_workspace_id, mine.account_id))
        self.assertIsNotNone(await self.accounts.get_workspace(theirs.default_workspace_id))
        self.assertIsNotNone(await self.keys.authenticate(their_key.secret))
        self.assertEqual(await self.accounts.member_role(theirs.default_workspace_id, theirs.account_id), "owner")
        self.assertEqual(
            [key.key_id for key in await self.keys.list_for_workspace(theirs.default_workspace_id)],
            [their_key.key.key_id],
        )

    async def test_a_second_delete_finds_nothing_and_is_not_an_error(self) -> None:
        await self._two_people()
        self.assertTrue(await self.deleter.delete_account("sub-1"))
        self.assertFalse(await self.deleter.delete_account("sub-1"))
        self.assertFalse(await self.deleter.delete_account("never-existed"))

    async def test_revoked_keys_go_too(self) -> None:
        mine, _, my_key, _ = await self._two_people()
        await self.keys.revoke(mine.default_workspace_id, my_key.key.key_id)

        await self.deleter.delete_account("sub-1")

        self.assertEqual(await self.keys.list_for_workspace(mine.default_workspace_id), [])

    async def test_there_is_no_identity_provider_to_delete_from(self) -> None:
        with self.assertLogs("videolens", level="INFO"):
            self.assertFalse(await self.deleter.delete_identity(str(uuid.uuid4())))


class SqlAccountDeleterTests(_DeleterBehaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database(_settings(database_url="sqlite://"))
        await self.database.create_all()
        self.accounts = SqlAccountDirectory(self.database)
        self.keys = SqlApiKeyRepository(self.database)
        self.deleter = SqlAccountDeleter(_settings(database_url="sqlite://"), self.database)

    async def asyncTearDown(self) -> None:
        await self.database.close()

    async def _add_member(self, workspace_id: str, account_id: str) -> None:
        async with self.database.connect() as conn:
            await conn.execute(
                insert(workspace_members).values(workspace_id=workspace_id, account_id=account_id, role="member")
            )

    async def _count(self, table) -> int:
        async with self.database.connect() as conn:
            return await conn.scalar(select(func.count()).select_from(table))

    async def test_row_counts_after_deletion(self) -> None:
        await self._two_people()
        await self.deleter.delete_account("sub-1")
        self.assertEqual(await self._count(accounts), 1)
        self.assertEqual(await self._count(workspaces), 1)
        self.assertEqual(await self._count(workspace_members), 1)
        self.assertEqual(await self._count(api_keys), 1)

    async def test_a_failure_part_way_rolls_the_whole_transaction_back(self) -> None:
        await self._two_people()

        class Boom(Exception):
            pass

        class FailsOnThirdStatement:
            """The real connection, except the third `execute` (after
            api_keys and memberships are gone) raises."""

            def __init__(self, conn) -> None:
                self._conn = conn
                self._calls = 0

            def __getattr__(self, name):
                return getattr(self._conn, name)

            async def execute(self, statement, *args, **kwargs):
                self._calls += 1
                if self._calls == 3:
                    raise Boom()
                return await self._conn.execute(statement, *args, **kwargs)

        original_connect = self.database.connect

        class Wrapped:
            def __init__(self) -> None:
                self._context = original_connect()

            async def __aenter__(self):
                return FailsOnThirdStatement(await self._context.__aenter__())

            async def __aexit__(self, *exc):
                return await self._context.__aexit__(*exc)

        with mock.patch.object(self.database, "connect", Wrapped):
            with self.assertRaises(Boom):
                await self.deleter.delete_account("sub-1")

        self.assertEqual(await self._count(accounts), 2)
        self.assertEqual(await self._count(api_keys), 2)
        self.assertEqual(await self._count(workspace_members), 3)


class InMemoryAccountDeleterTests(_DeleterBehaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.accounts = InMemoryAccountDirectory()
        self.keys = InMemoryApiKeyRepository()
        self.deleter = InMemoryAccountDeleter(_settings(), accounts=self.accounts, api_keys=self.keys)

    async def _add_member(self, workspace_id: str, account_id: str) -> None:
        self.accounts._members[(workspace_id, account_id)] = "member"

    async def test_disabled_store_reports_disabled(self) -> None:
        accounts = InMemoryAccountDirectory(enabled=False)
        deleter = InMemoryAccountDeleter(_settings(), accounts=accounts, api_keys=InMemoryApiKeyRepository())
        self.assertFalse(deleter.enabled)


class _FirstSightBehaviour:
    """A token that outlived its deleted user must not re-create the account.
    Mixed into a TestCase whose asyncSetUp sets self.users and
    self.accounts (built with users=self.users) and implements `_rows()`."""

    async def test_a_gone_user_gets_401_and_nothing_is_written(self) -> None:
        self.users.gone.add("sub-gone")

        with self.assertRaises(AuthenticationError) as caught:
            await self.accounts.resolve_account("sub-gone", "x@b.test")

        self.assertEqual(str(caught.exception), "Invalid access token.")
        self.assertEqual(await self._rows(), 0)

    async def test_first_sight_asks_once_and_later_reads_never_ask(self) -> None:
        first = await self.accounts.resolve_account("sub-1")
        again = await self.accounts.resolve_account("sub-1", "new@b.test")

        self.assertEqual(first.account_id, again.account_id)
        self.assertEqual(self.users.asked, ["sub-1"])

    async def test_an_existing_account_is_unaffected_by_a_gone_user(self) -> None:
        # The check guards creation only. An account that still has rows
        # (deletion not yet run, or failed at the rows step) reads normally,
        # so a retry of DELETE /api/me can still resolve the person.
        account = await self.accounts.resolve_account("sub-1")
        self.users.gone.add("sub-1")

        again = await self.accounts.resolve_account("sub-1")

        self.assertEqual(again.account_id, account.account_id)
        self.assertEqual(self.users.asked, ["sub-1"])


class SqlFirstSightTests(_FirstSightBehaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database(_settings(database_url="sqlite://"))
        await self.database.create_all()
        self.users = _Users()
        self.accounts = SqlAccountDirectory(self.database, users=self.users)

    async def asyncTearDown(self) -> None:
        await self.database.close()

    async def _rows(self) -> int:
        async with self.database.connect() as conn:
            total = 0
            for table in (accounts, workspaces, workspace_members):
                total += await conn.scalar(select(func.count()).select_from(table))
            return total


class InMemoryFirstSightTests(_FirstSightBehaviour, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.users = _Users()
        self.accounts = InMemoryAccountDirectory(users=self.users)

    async def _rows(self) -> int:
        return len(self.accounts._accounts) + len(self.accounts._workspaces) + len(self.accounts._members)


class _FakeConn:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict]] = []
        self.scalar_result = True

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))

    async def scalar(self, statement, params=None):
        self.statements.append((str(statement), params or {}))
        return self.scalar_result


class _FakePostgres:
    """Enough of `Database` for `delete_identity`'s Postgres branch."""

    enabled = True
    dialect = "postgresql"

    def __init__(self) -> None:
        self.conn = _FakeConn()

    def connect(self):
        conn = self.conn

        class _Context:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Context()


class PostgresIdentityStepTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_the_definer_function_with_the_subject_uuid(self) -> None:
        database = _FakePostgres()
        deleter = SqlAccountDeleter(_settings(), database)  # type: ignore[arg-type]
        subject = str(uuid.uuid4())

        self.assertTrue(await deleter.delete_identity(subject))

        [(sql, params)] = database.conn.statements
        self.assertIn("videolens_private.delete_auth_user", sql)
        self.assertNotIn("auth.users", sql)
        self.assertEqual(params, {"user_id": subject})

    async def test_a_non_uuid_subject_is_skipped_without_a_query(self) -> None:
        database = _FakePostgres()
        deleter = SqlAccountDeleter(_settings(), database)  # type: ignore[arg-type]

        with self.assertLogs("videolens", level="WARNING"):
            self.assertFalse(await deleter.delete_identity("github|12345"))
        self.assertEqual(database.conn.statements, [])


class IdentityProviderUsersTests(unittest.IsolatedAsyncioTestCase):
    async def test_postgres_asks_the_definer_function(self) -> None:
        database = _FakePostgres()
        users = SqlIdentityProviderUsers(_settings(), database)  # type: ignore[arg-type]
        subject = str(uuid.uuid4())

        self.assertTrue(await users.exists(subject))
        database.conn.scalar_result = False
        self.assertFalse(await users.exists(subject))

        sql, params = database.conn.statements[0]
        self.assertIn("videolens_private.auth_user_exists", sql)
        self.assertEqual(params, {"user_id": subject})

    async def test_postgres_treats_a_non_uuid_subject_as_gone_without_a_query(self) -> None:
        database = _FakePostgres()
        users = SqlIdentityProviderUsers(_settings(), database)  # type: ignore[arg-type]
        self.assertFalse(await users.exists("github|12345"))
        self.assertEqual(database.conn.statements, [])

    async def test_sqlite_and_in_memory_have_no_provider_so_everyone_exists(self) -> None:
        database = Database(_settings(database_url="sqlite://"))
        try:
            self.assertTrue(await SqlIdentityProviderUsers(_settings(), database).exists("anything"))
        finally:
            await database.close()
        self.assertTrue(await AlwaysPresentIdentityProviderUsers(_settings()).exists("anything"))


def _load_migration():
    path = BACKEND / "migrations" / "versions" / "0002_auth_user_deleter.py"
    spec = importlib.util.spec_from_file_location("migration_0002_auth_user_deleter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthUserDeleterMigrationTests(unittest.TestCase):
    """`0002_auth_user_deleter` with Alembic's `op` and `context` mocked."""

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

    def _answers(
        self, *, role: bool = True, can_execute: bool = True, rest_usage: bool = False, exists_executable: bool = True
    ) -> None:
        def execute(statement, params=None):
            sql = str(statement)
            result = mock.MagicMock()
            if "pg_roles" in sql:
                result.scalar.return_value = 1 if (params or {}).get("role") != "videolens_api" or role else None
            elif "has_function_privilege" in sql:
                if "auth_user_exists" in (params or {}).get("function", ""):
                    result.scalar.return_value = exists_executable
                else:
                    result.scalar.return_value = can_execute
            elif "has_schema_privilege" in sql:
                result.scalar.return_value = rest_usage
            return result

        self.op.get_bind.return_value.execute.side_effect = execute

    def _ddl(self) -> str:
        return "\n".join(str(call.args[0]) for call in self.op.execute.call_args_list)

    def test_chains_after_0001(self) -> None:
        self.assertEqual(self.migration.revision, "0002_auth_user_deleter")
        self.assertEqual(self.migration.down_revision, "0001_identity")

    def test_creates_a_locked_down_definer_function(self) -> None:
        self._answers()
        self.migration.upgrade()
        ddl = self._ddl()
        self.assertIn("CREATE SCHEMA IF NOT EXISTS videolens_private", ddl)
        self.assertIn("REVOKE ALL ON SCHEMA videolens_private FROM PUBLIC", ddl)
        self.assertIn("GRANT USAGE ON SCHEMA videolens_private TO videolens_api", ddl)
        self.assertIn("CREATE OR REPLACE FUNCTION videolens_private.delete_auth_user(target uuid)", ddl)
        self.assertIn("SECURITY DEFINER", ddl)
        self.assertIn("SET search_path = ''", ddl)
        self.assertIn("DELETE FROM auth.users WHERE id = target", ddl)
        self.assertIn("REVOKE ALL ON FUNCTION videolens_private.delete_auth_user(uuid) FROM PUBLIC", ddl)
        self.assertIn("GRANT EXECUTE ON FUNCTION videolens_private.delete_auth_user(uuid) TO videolens_api", ddl)
        # The revoke from PUBLIC comes before the grant to the backend role.
        self.assertLess(ddl.index("REVOKE ALL ON FUNCTION"), ddl.index("GRANT EXECUTE ON FUNCTION"))

    def test_creates_the_read_only_existence_check_with_the_same_lockdown(self) -> None:
        self._answers()
        self.migration.upgrade()
        ddl = self._ddl()
        self.assertIn("CREATE OR REPLACE FUNCTION videolens_private.auth_user_exists(target uuid)", ddl)
        self.assertIn("RETURNS boolean", ddl)
        self.assertIn("STABLE", ddl)
        self.assertIn("SELECT EXISTS (SELECT 1 FROM auth.users WHERE id = target)", ddl)
        self.assertEqual(ddl.count("SECURITY DEFINER"), 2)
        self.assertEqual(ddl.count("SET search_path = ''"), 2)
        self.assertIn("REVOKE ALL ON FUNCTION videolens_private.auth_user_exists(uuid) FROM PUBLIC", ddl)
        self.assertIn("GRANT EXECUTE ON FUNCTION videolens_private.auth_user_exists(uuid) TO videolens_api", ddl)
        self.assertLess(
            ddl.index("REVOKE ALL ON FUNCTION videolens_private.auth_user_exists"),
            ddl.index("GRANT EXECUTE ON FUNCTION videolens_private.auth_user_exists"),
        )

    def test_verify_checks_both_functions(self) -> None:
        self._answers()
        self.migration.upgrade()
        checked = [
            call.args[1]["function"]
            for call in self.op.get_bind.return_value.execute.call_args_list
            if "has_function_privilege" in str(call.args[0])
        ]
        self.assertEqual(
            checked,
            ["videolens_private.delete_auth_user(uuid)", "videolens_private.auth_user_exists(uuid)"],
        )

    def test_fails_loudly_when_the_existence_check_is_not_executable(self) -> None:
        self._answers(exists_executable=False)
        with self.assertRaises(RuntimeError) as caught:
            self.migration.upgrade()
        self.assertIn("auth_user_exists", str(caught.exception))

    def test_a_missing_role_fails_before_any_ddl(self) -> None:
        self._answers(role=False)
        with self.assertRaises(RuntimeError) as caught:
            self.migration.upgrade()
        self.assertIn("DATABASE_APP_ROLE", str(caught.exception))
        self.op.execute.assert_not_called()

    def test_fails_loudly_when_the_backend_role_cannot_execute(self) -> None:
        self._answers(can_execute=False)
        with self.assertRaises(RuntimeError) as caught:
            self.migration.upgrade()
        self.assertIn("cannot execute", str(caught.exception))

    def test_fails_when_a_rest_role_can_reach_the_schema(self) -> None:
        self._answers(rest_usage=True)
        with self.assertRaises(RuntimeError) as caught:
            self.migration.upgrade()
        self.assertIn("USAGE on videolens_private", str(caught.exception))

    def test_offline_rendering_skips_the_live_checks(self) -> None:
        self.context.is_offline_mode.return_value = True
        self.migration.upgrade()
        self.op.get_bind.return_value.execute.assert_not_called()
        self.assertIn("SECURITY DEFINER", self._ddl())

    def test_sqlite_is_a_no_op_both_ways(self) -> None:
        self.op.get_bind.return_value.dialect.name = "sqlite"
        self.migration.upgrade()
        self.migration.downgrade()
        self.op.execute.assert_not_called()

    def test_downgrade_drops_the_function_then_the_schema(self) -> None:
        self.migration.downgrade()
        ddl = self._ddl()
        self.assertIn("DROP FUNCTION IF EXISTS videolens_private.delete_auth_user(uuid)", ddl)
        self.assertIn("DROP FUNCTION IF EXISTS videolens_private.auth_user_exists(uuid)", ddl)
        self.assertLess(ddl.index("DROP FUNCTION IF EXISTS videolens_private.auth_user_exists"), ddl.index("DROP SCHEMA"))
        self.assertIn("DROP SCHEMA IF EXISTS videolens_private", ddl)
        self.assertNotIn("CASCADE", ddl)
        self.assertLess(ddl.index("DROP FUNCTION"), ddl.index("DROP SCHEMA"))

    def test_the_role_name_must_be_a_plain_identifier(self) -> None:
        with mock.patch.dict(os.environ, {"DATABASE_APP_ROLE": "x; DROP SCHEMA auth"}):
            with self.assertRaises(ValueError):
                self.migration.upgrade()
        self.op.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
