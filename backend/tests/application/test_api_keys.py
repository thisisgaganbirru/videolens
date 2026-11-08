"""The create / list / revoke use cases and the gate they share."""

import unittest

from app.application.create_api_key import CreateApiKeyUseCase
from app.application.entitlements import EntitlementResolver
from app.application.get_account import GetAccountUseCase
from app.application.list_api_keys import ListApiKeysUseCase
from app.application.revoke_api_key import RevokeApiKeyUseCase
from app.domain.entities import AuthMethod, Principal
from app.domain.entitlements import Plan
from app.domain.errors import AccountsNotConfiguredError, ApiKeyLimitError, ApiKeyNotFoundError, ForbiddenError
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository


class ApiKeyUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.accounts = InMemoryAccountDirectory()
        self.keys = InMemoryApiKeyRepository()
        self.create = CreateApiKeyUseCase(api_keys=self.keys, accounts=self.accounts, max_active=2)
        self.list = ListApiKeysUseCase(api_keys=self.keys, accounts=self.accounts)
        self.revoke = RevokeApiKeyUseCase(api_keys=self.keys, accounts=self.accounts)
        account = await self.accounts.resolve_account("user-123")
        self.person = Principal(
            subject="user:user-123",
            authenticated=True,
            method=AuthMethod.TOKEN,
            account_id=account.account_id,
            workspace_id=account.default_workspace_id,
        )

    async def test_a_signed_in_person_creates_lists_and_revokes(self) -> None:
        created = await self.create.execute(self.person, "  laptop  ")

        self.assertTrue(created.secret.startswith("vl_live_"))
        self.assertEqual(created.key.name, "laptop")
        self.assertTrue(created.secret.startswith(created.key.prefix))
        listed = await self.list.execute(self.person)
        self.assertEqual([key.key_id for key in listed], [created.key.key_id])

        await self.revoke.execute(self.person, created.key.key_id)
        self.assertFalse((await self.list.execute(self.person))[0].active)

    async def test_there_is_no_plan_gate_on_creation(self) -> None:
        # The old branch refused keys on the free plan; this phase does not.
        created = await self.create.execute(self.person, "")
        self.assertEqual(created.key.name, "Unnamed key")

    async def test_names_are_trimmed_to_eighty_characters(self) -> None:
        created = await self.create.execute(self.person, "n" * 200)
        self.assertEqual(len(created.key.name), 80)

    async def test_the_cap_counts_live_keys_only(self) -> None:
        first = await self.create.execute(self.person, "a")
        await self.create.execute(self.person, "b")
        with self.assertRaises(ApiKeyLimitError):
            await self.create.execute(self.person, "c")

        await self.revoke.execute(self.person, first.key.key_id)
        await self.create.execute(self.person, "c")

    async def test_an_api_key_principal_can_never_manage_keys(self) -> None:
        agent = Principal(
            subject="key:k1",
            authenticated=True,
            method=AuthMethod.API_KEY,
            account_id=self.person.account_id,
            workspace_id=self.person.workspace_id,
        )
        for call in (self.create.execute(agent, "x"), self.list.execute(agent), self.revoke.execute(agent, "k1")):
            with self.assertRaises(ForbiddenError):
                await call

    async def test_a_member_who_is_not_the_owner_cannot_create_or_revoke(self) -> None:
        stranger = Principal(
            subject="user:someone-else",
            authenticated=True,
            method=AuthMethod.TOKEN,
            account_id="acct-not-a-member",
            workspace_id=self.person.workspace_id,
        )
        with self.assertRaises(ForbiddenError):
            await self.create.execute(stranger, "x")
        with self.assertRaises(ForbiddenError):
            await self.revoke.execute(stranger, "k1")

    async def test_revoking_another_workspaces_key_is_not_found(self) -> None:
        other = await self.accounts.resolve_account("user-999")
        foreign = await self.keys.issue(other.default_workspace_id, "theirs", ["runs:read"], max_active=10)

        with self.assertRaises(ApiKeyNotFoundError):
            await self.revoke.execute(self.person, foreign.key.key_id)
        with self.assertRaises(ApiKeyNotFoundError):
            await self.revoke.execute(self.person, "no-such-key")

    async def test_no_account_store_is_a_configuration_error(self) -> None:
        accounts = InMemoryAccountDirectory(enabled=False)
        use_case = ListApiKeysUseCase(api_keys=InMemoryApiKeyRepository(enabled=False), accounts=accounts)
        bare = Principal(subject="user:user-123", authenticated=True, method=AuthMethod.TOKEN)
        with self.assertRaises(AccountsNotConfiguredError):
            await use_case.execute(bare)


class GetAccountTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_the_single_free_entitlement_with_deployment_limits(self) -> None:
        accounts = InMemoryAccountDirectory()
        account = await accounts.resolve_account("user-123", "a@b.test")
        principal = Principal(
            subject="user:user-123",
            authenticated=True,
            method=AuthMethod.TOKEN,
            account_id=account.account_id,
            workspace_id=account.default_workspace_id,
        )
        use_case = GetAccountUseCase(
            accounts=accounts, entitlements=EntitlementResolver(max_duration_seconds=180, max_file_size_mb=200)
        )

        view = await use_case.execute(principal)

        self.assertEqual(view.workspace.workspace_id, account.default_workspace_id)
        self.assertIs(view.entitlement.plan, Plan.FREE)
        self.assertEqual(view.entitlement.max_duration_seconds, 180)
        self.assertEqual(view.entitlement.max_file_size_mb, 200)
        self.assertFalse(view.entitlement.metered)
        self.assertTrue(view.entitlement.api_access)
        self.assertFalse(view.entitlement.library)
        self.assertTrue(view.accounts_enabled)


if __name__ == "__main__":
    unittest.main()
