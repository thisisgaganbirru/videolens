import unittest

from app.application.identify_caller import IdentifyCallerUseCase
from app.domain.entities import AuthMethod
from app.domain.entitlements import Plan
from app.domain.errors import AuthenticationError

from .fakes import FakeAccountDirectory, FakeApiKeyRepository, make_workspace


class IdentifyCallerTests(unittest.IsolatedAsyncioTestCase):
    def _use_case(self, accounts=None, api_keys=None) -> IdentifyCallerUseCase:
        return IdentifyCallerUseCase(
            accounts=accounts or FakeAccountDirectory(), api_keys=api_keys or FakeApiKeyRepository()
        )

    async def test_token_without_a_database_is_a_plain_signed_in_principal(self) -> None:
        use_case = self._use_case(accounts=FakeAccountDirectory(enabled=False))

        principal = await use_case.from_token_claims({"sub": "user_123", "email": "a@b.test"})

        self.assertEqual(principal.subject, "user:user_123")
        self.assertTrue(principal.authenticated)
        self.assertIs(principal.method, AuthMethod.TOKEN)
        self.assertIsNone(principal.workspace_id)
        self.assertIs(principal.plan, Plan.FREE)
        self.assertEqual(principal.email, "a@b.test")
        # Ownership stays keyed by subject, exactly as before plans existed.
        self.assertEqual(principal.owner_id, "user:user_123")

    async def test_token_with_a_database_resolves_the_account_and_default_workspace(self) -> None:
        accounts = FakeAccountDirectory()
        use_case = self._use_case(accounts=accounts)

        principal = await use_case.from_token_claims({"sub": "user_123", "email": "a@b.test"})
        again = await use_case.from_token_claims({"sub": "user_123"})

        self.assertEqual(principal.account_id, "acct-1")
        self.assertEqual(principal.workspace_id, "ws-1")
        self.assertEqual(principal.owner_id, "workspace:ws-1")
        self.assertIs(principal.plan, Plan.FREE)
        # Same subject, same account: the directory is the source of truth,
        # and the email survives a token that omits it.
        self.assertEqual(again.account_id, "acct-1")
        self.assertEqual(again.email, "a@b.test")

    async def test_token_without_a_subject_is_rejected(self) -> None:
        with self.assertRaises(AuthenticationError):
            await self._use_case().from_token_claims({"email": "a@b.test"})
        with self.assertRaises(AuthenticationError):
            await self._use_case().from_token_claims({"sub": "  "})

    async def test_api_key_maps_to_its_workspace_and_plan(self) -> None:
        accounts = FakeAccountDirectory()
        accounts.add_workspace(make_workspace(plan=Plan.STUDIO))
        api_keys = FakeApiKeyRepository()
        issued = await api_keys.issue("ws-pro", "ci", ["runs:write"])
        use_case = self._use_case(accounts=accounts, api_keys=api_keys)

        principal = await use_case.from_api_key(f"  {issued.secret} ")

        self.assertEqual(principal.subject, f"key:{issued.key.key_id}")
        self.assertIs(principal.method, AuthMethod.API_KEY)
        self.assertTrue(principal.authenticated)
        self.assertIsNone(principal.account_id)
        self.assertEqual(principal.workspace_id, "ws-pro")
        self.assertIs(principal.plan, Plan.STUDIO)
        self.assertEqual(principal.owner_id, "workspace:ws-pro")

    async def test_unknown_revoked_or_orphaned_api_keys_are_rejected(self) -> None:
        accounts = FakeAccountDirectory()
        accounts.add_workspace(make_workspace(plan=Plan.STUDIO))
        api_keys = FakeApiKeyRepository()
        use_case = self._use_case(accounts=accounts, api_keys=api_keys)

        with self.assertRaises(AuthenticationError):
            await use_case.from_api_key("vl_live_nope")

        issued = await api_keys.issue("ws-pro", "ci", ["runs:write"])
        await api_keys.revoke("ws-pro", issued.key.key_id)
        with self.assertRaises(AuthenticationError):
            await use_case.from_api_key(issued.secret)

        orphan = await api_keys.issue("ws-gone", "ci", ["runs:write"])
        with self.assertRaises(AuthenticationError):
            await use_case.from_api_key(orphan.secret)

    def test_client_id_is_anonymous_and_validated(self) -> None:
        principal = IdentifyCallerUseCase.from_client_id("client-0123456789abcdef")

        self.assertEqual(principal.subject, "client:client-0123456789abcdef")
        self.assertFalse(principal.authenticated)
        self.assertIs(principal.method, AuthMethod.ANONYMOUS)
        with self.assertRaises(AuthenticationError):
            IdentifyCallerUseCase.from_client_id("short")


if __name__ == "__main__":
    unittest.main()
