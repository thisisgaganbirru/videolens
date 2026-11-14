"""`DeleteAccountUseCase`: who may delete, in what order, and what a
partial failure or a repeat call leaves behind."""

import unittest

from app.application.delete_account import DeleteAccountUseCase
from app.domain.entities import AuthMethod, Principal
from app.domain.errors import AccountDeletionError, AccountsNotConfiguredError, ForbiddenError
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_deleter import InMemoryAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository

from .fakes import FakeAccountDeleter, FakeRunRepository


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
            accounts=self.accounts, deleter=self.deleter, api_keys=self.keys, runs=self.runs
        )
        self.person = _person(await self.accounts.resolve_account("sub-1", "a@b.test"))

    async def test_runs_then_rows_then_identity_last(self) -> None:
        key = await self.keys.issue(self.person.workspace_id, "ci", [], max_active=10)

        await self.use_case.execute(self.person)

        self.assertEqual(
            self.log,
            ["runs:user:sub-1", f"runs:key:{key.key.key_id}", "rows:sub-1", "identity:sub-1"],
        )

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

    async def test_a_row_failure_is_a_500_and_the_identity_is_kept(self) -> None:
        self.deleter.rows_error = RuntimeError("connection reset by db.internal")

        with self.assertLogs("videolens", level="ERROR"), self.assertRaises(AccountDeletionError) as caught:
            await self.use_case.execute(self.person)

        self.assertNotIn("db.internal", str(caught.exception))
        self.assertIn("RuntimeError", caught.exception.log_detail)
        self.assertNotIn("identity:sub-1", self.log)

    async def test_an_identity_failure_is_a_500_after_the_rows_went(self) -> None:
        self.deleter.identity_error = RuntimeError("permission denied for table users")

        with self.assertLogs("videolens", level="ERROR"), self.assertRaises(AccountDeletionError) as caught:
            await self.use_case.execute(self.person)

        self.assertNotIn("permission", str(caught.exception))
        self.assertEqual(self.log[-2:], ["rows:sub-1", "identity:sub-1"])

    async def test_a_run_store_failure_does_not_stop_the_deletion(self) -> None:
        async def broken(owner_id: str) -> int:
            raise ConnectionError("redis down")

        self.runs.delete_for_owner = broken  # type: ignore[method-assign]

        with self.assertLogs("videolens", level="WARNING"):
            await self.use_case.execute(self.person)

        self.assertEqual(self.log, ["rows:sub-1", "identity:sub-1"])

    async def test_an_already_deleted_account_is_not_an_error(self) -> None:
        self.deleter.rows_exist = False

        await self.use_case.execute(self.person)
        await self.use_case.execute(self.person)

        # The identity step still runs: a retry after an identity failure
        # finds no rows but must still remove the provider user.
        self.assertEqual(self.log.count("identity:sub-1"), 2)

    async def test_a_skipped_identity_step_still_succeeds(self) -> None:
        self.deleter.identity_supported = False
        await self.use_case.execute(self.person)
        self.assertIn("identity:sub-1", self.log)


class DeleteAccountInMemoryTests(unittest.IsolatedAsyncioTestCase):
    """End to end over the in-memory adapters a local `uvicorn` uses."""

    async def test_the_person_goes_and_everyone_else_stays(self) -> None:
        accounts = InMemoryAccountDirectory()
        keys = InMemoryApiKeyRepository()
        runs = FakeRunRepository()
        use_case = DeleteAccountUseCase(
            accounts=accounts,
            deleter=InMemoryAccountDeleter(Settings(_env_file=None), accounts=accounts, api_keys=keys),
            api_keys=keys,
            runs=runs,
        )
        mine = await accounts.resolve_account("sub-1")
        theirs = await accounts.resolve_account("sub-2")
        my_key = await keys.issue(mine.default_workspace_id, "mine", [], max_active=10)
        their_key = await keys.issue(theirs.default_workspace_id, "theirs", [], max_active=10)
        await runs.create("by-key", f"key:{my_key.key.key_id}")
        await runs.create("their-run", "user:sub-2")
        person = _person(mine)

        await use_case.execute(person)
        await use_case.execute(person)  # idempotent

        self.assertIsNone(await accounts.get_workspace(mine.default_workspace_id))
        self.assertIsNone(await keys.authenticate(my_key.secret))
        self.assertIsNotNone(await keys.authenticate(their_key.secret))
        self.assertIsNotNone(await accounts.get_workspace(theirs.default_workspace_id))
        self.assertEqual(sorted(runs.runs), ["their-run"])
        again = await accounts.resolve_account("sub-1")
        self.assertNotEqual(again.account_id, mine.account_id)


if __name__ == "__main__":
    unittest.main()
