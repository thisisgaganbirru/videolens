"""`DeleteAccountUseCase`: who may delete, what the 30-day hold changes at
once, and what a failure or a repeat call leaves behind
(docs/backend/saved-history.md)."""

import unittest
from datetime import datetime, timedelta, timezone

from app.application.delete_account import DeleteAccountUseCase
from app.domain.entities import AuthMethod, Principal
from app.domain.errors import AccountDeletionError, AccountsNotConfiguredError, ForbiddenError
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_deleter import InMemoryAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository

from .fakes import FakeAccountDeleter, FakeRunRepository

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def _person(account) -> Principal:
    return Principal(
        subject=f"user:{account.external_id}",
        authenticated=True,
        method=AuthMethod.TOKEN,
        account_id=account.account_id,
        workspace_id=account.default_workspace_id,
    )


class DeleteAccountUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.log: list[str] = []
        self.accounts = InMemoryAccountDirectory()
        self.keys = InMemoryApiKeyRepository()
        self.runs = FakeRunRepository()
        original = self.runs.delete_for_owner

        async def logged_delete(owner_id: str) -> int:
            self.log.append(f"runs:{owner_id}")
            return await original(owner_id)

        self.runs.delete_for_owner = logged_delete  # type: ignore[method-assign]
        self.deleter = FakeAccountDeleter(self.log)
        self.use_case = DeleteAccountUseCase(
            accounts=self.accounts,
            deleter=self.deleter,
            api_keys=self.keys,
            runs=self.runs,
            hold_days=30,
            clock=lambda: NOW,
        )
        self.person = _person(await self.accounts.resolve_account("sub-1", "a@b.test"))

    async def test_runs_then_the_hold_and_nothing_is_removed_for_good(self) -> None:
        key = await self.keys.issue(self.person.workspace_id, "ci", [], max_active=10)

        purge_at = await self.use_case.execute(self.person)

        self.assertEqual(self.log, ["runs:user:sub-1", f"runs:key:{key.key.key_id}", "hold:sub-1"])
        self.assertEqual(purge_at, NOW + timedelta(days=30))
        # The Supabase user and the rows stay until the hold ends.
        self.assertNotIn("identity:sub-1", self.log)
        self.assertNotIn("rows:sub-1", self.log)

    async def test_only_the_persons_runs_are_deleted(self) -> None:
        await self.runs.create("mine", "user:sub-1")
        await self.runs.create("theirs", "user:sub-2")
        await self.runs.create("anon", "client:someone")

        await self.use_case.execute(self.person)

        self.assertEqual(sorted(self.runs.runs), ["anon", "theirs"])

    async def test_an_api_key_cannot_delete_its_owner(self) -> None:
        agent = Principal(
            subject="key:k1",
            authenticated=True,
            method=AuthMethod.API_KEY,
            account_id=self.person.account_id,
            workspace_id=self.person.workspace_id,
        )
        with self.assertRaises(ForbiddenError):
            await self.use_case.execute(agent)
        self.assertEqual(self.log, [])

    async def test_no_account_store_is_not_configured_and_deletes_nothing(self) -> None:
        for accounts_on, deleter_on in ((False, True), (True, False)):
            with self.subTest(accounts=accounts_on, deleter=deleter_on):
                log: list[str] = []
                use_case = DeleteAccountUseCase(
                    accounts=InMemoryAccountDirectory(enabled=accounts_on),
                    deleter=FakeAccountDeleter(log, enabled=deleter_on),
                    api_keys=self.keys,
                    runs=self.runs,
                )
                with self.assertRaises(AccountsNotConfiguredError):
                    await use_case.execute(self.person)
                self.assertEqual(log, [])
        self.assertEqual(self.log, [])

    async def test_a_hold_failure_is_a_500_without_internals(self) -> None:
        self.deleter.hold_error = RuntimeError("connection reset by db.internal")

        with self.assertLogs("videolens", level="ERROR"), self.assertRaises(AccountDeletionError) as caught:
            await self.use_case.execute(self.person)

        self.assertNotIn("db.internal", str(caught.exception))
        self.assertIn("RuntimeError", caught.exception.log_detail)
        self.assertNotIn("identity:sub-1", self.log)

    async def test_a_run_store_failure_does_not_stop_the_deletion(self) -> None:
        async def broken(owner_id: str) -> int:
            raise ConnectionError("redis down")

        self.runs.delete_for_owner = broken  # type: ignore[method-assign]

        with self.assertLogs("videolens", level="WARNING"):
            await self.use_case.execute(self.person)

        self.assertEqual(self.log, ["hold:sub-1"])

    async def test_a_repeat_keeps_the_first_deadline(self) -> None:
        first = await self.use_case.execute(self.person)
        later = DeleteAccountUseCase(
            accounts=self.accounts,
            deleter=self.deleter,
            api_keys=self.keys,
            runs=self.runs,
            clock=lambda: NOW + timedelta(days=5),
        )
        self.assertEqual(await later.execute(self.person), first)

    async def test_hold_days_comes_from_the_setting(self) -> None:
        use_case = DeleteAccountUseCase(
            accounts=self.accounts,
            deleter=FakeAccountDeleter(),
            api_keys=self.keys,
            runs=self.runs,
            hold_days=7,
            clock=lambda: NOW,
        )
        self.assertEqual(await use_case.execute(self.person), NOW + timedelta(days=7))


class DeleteAccountInMemoryTests(unittest.IsolatedAsyncioTestCase):
    """End to end over the in-memory adapters a local `uvicorn` uses."""

    async def test_the_person_is_held_and_everyone_else_is_untouched(self) -> None:
        accounts = InMemoryAccountDirectory()
        keys = InMemoryApiKeyRepository()
        runs = FakeRunRepository()
        deleter = InMemoryAccountDeleter(Settings(_env_file=None), accounts=accounts, api_keys=keys)
        use_case = DeleteAccountUseCase(
            accounts=accounts, deleter=deleter, api_keys=keys, runs=runs, clock=lambda: NOW
        )
        mine = await accounts.resolve_account("sub-1")
        theirs = await accounts.resolve_account("sub-2")
        my_key = await keys.issue(mine.default_workspace_id, "mine", [], max_active=10)
        their_key = await keys.issue(theirs.default_workspace_id, "theirs", [], max_active=10)
        await runs.create("by-key", f"key:{my_key.key.key_id}")
        await runs.create("their-run", "user:sub-2")
        person = _person(mine)

        purge_at = await use_case.execute(person)
        self.assertEqual(await use_case.execute(person), purge_at)  # idempotent

        held = await accounts.resolve_account("sub-1")
        self.assertEqual(held.account_id, mine.account_id)
        self.assertTrue(held.pending_deletion)
        self.assertEqual(held.purge_at, NOW + timedelta(days=30))
        # Rows are kept (hidden by the caller checks), the key too.
        self.assertIsNotNone(await accounts.get_workspace(mine.default_workspace_id))
        self.assertFalse((await accounts.resolve_account("sub-2")).pending_deletion)
        self.assertIsNotNone(await keys.authenticate(their_key.secret))
        self.assertEqual(sorted(runs.runs), ["their-run"])

        # After the hold, removal for good: a later sign-in is a new account.
        self.assertEqual(
            [p.external_id for p in await deleter.due_for_purge(NOW + timedelta(days=31), limit=10)], ["sub-1"]
        )
        self.assertTrue(await deleter.delete_account("sub-1", due_before=NOW + timedelta(days=31)))
        self.assertIsNone(await keys.authenticate(my_key.secret))
        again = await accounts.resolve_account("sub-1")
        self.assertNotEqual(again.account_id, mine.account_id)

    async def test_purge_is_refused_before_the_deadline(self) -> None:
        accounts = InMemoryAccountDirectory()
        keys = InMemoryApiKeyRepository()
        deleter = InMemoryAccountDeleter(Settings(_env_file=None), accounts=accounts, api_keys=keys)
        mine = await accounts.resolve_account("sub-1")
        await deleter.schedule_deletion("sub-1", now=NOW, purge_at=NOW + timedelta(days=30))

        self.assertFalse(await deleter.delete_account("sub-1", due_before=NOW + timedelta(days=29)))
        self.assertEqual((await accounts.resolve_account("sub-1")).account_id, mine.account_id)


if __name__ == "__main__":
    unittest.main()
