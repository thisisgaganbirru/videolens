import unittest

from app.application.identify_caller import IdentifyCallerUseCase
from app.domain.entities import AuthMethod
from app.domain.errors import AuthenticationError, AuthNotConfiguredError, ClientIdInvalidError
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository

from .fakes import FakeTokenVerifier

CLIENT_ID = "client-0123456789abcdef"


class IdentifyCallerTests(unittest.IsolatedAsyncioTestCase):
    """The in-memory adapters stand in for the account store: they are the
    real local-mode adapters and share their rules with the SQL ones
    (`tests/infrastructure/persistence/test_sql_adapters.py` runs both)."""

    def setUp(self) -> None:
        self.accounts = InMemoryAccountDirectory()
        self.api_keys = InMemoryApiKeyRepository()
        self.verifier = FakeTokenVerifier({"sub": "user-123", "email": "a@b.test", "role": "authenticated"})

    def _use_case(self, *, allow_anonymous: bool = True, accounts=None, api_keys=None) -> IdentifyCallerUseCase:
        return IdentifyCallerUseCase(
            accounts=accounts or self.accounts,
            api_keys=api_keys or self.api_keys,
            verifier=self.verifier,
            allow_anonymous=allow_anonymous,
        )

    async def _issue_key(self) -> tuple[str, str, str]:
        account = await self.accounts.resolve_account("user-123", "a@b.test")
        created = await self.api_keys.issue(account.default_workspace_id, "ci", ["runs:read"], max_active=10)
        return created.secret, account.account_id, account.default_workspace_id

    # -- anonymous -------------------------------------------------------

    async def test_client_id_is_an_anonymous_principal(self) -> None:
        principal = await self._use_case().resolve(client_id=CLIENT_ID)

        self.assertEqual(principal.subject, f"client:{CLIENT_ID}")
        self.assertFalse(principal.authenticated)
        self.assertIs(principal.method, AuthMethod.ANONYMOUS)
        self.assertEqual(principal.owner_id, f"client:{CLIENT_ID}")
        self.assertEqual(self.verifier.tokens, [])

    async def test_malformed_or_missing_client_id_is_a_bad_request(self) -> None:
        for client_id in ("", "short", "has spaces in it 0123456789", "x" * 129):
            with self.subTest(client_id=client_id), self.assertRaises(ClientIdInvalidError):
                await self._use_case().resolve(client_id=client_id)

    async def test_anonymous_refused_when_the_deployment_disallows_it(self) -> None:
        with self.assertRaises(AuthenticationError):
            await self._use_case(allow_anonymous=False).resolve(client_id=CLIENT_ID)

    async def test_allow_anonymous_off_still_accepts_credentials(self) -> None:
        principal = await self._use_case(allow_anonymous=False).resolve(authorization="Bearer eyJhbGciOi.x.y")
        self.assertIs(principal.method, AuthMethod.TOKEN)

    async def test_an_empty_bearer_is_treated_as_no_credential(self) -> None:
        principal = await self._use_case().resolve(authorization="Bearer   ", client_id=CLIENT_ID)
        self.assertIs(principal.method, AuthMethod.ANONYMOUS)

    # -- identity-provider token -----------------------------------------

    async def test_token_resolves_the_account_and_its_default_workspace(self) -> None:
        use_case = self._use_case()

        principal = await use_case.resolve(authorization="Bearer eyJhbGciOi.x.y", client_id=CLIENT_ID)
        again = await use_case.resolve(authorization="Bearer eyJhbGciOi.other.token")

        self.assertEqual(principal.subject, "user:user-123")
        self.assertTrue(principal.authenticated)
        self.assertIs(principal.method, AuthMethod.TOKEN)
        self.assertIsNotNone(principal.account_id)
        self.assertIsNotNone(principal.workspace_id)
        self.assertEqual(principal.email, "a@b.test")
        # Same subject, same account and workspace, whatever the token.
        self.assertEqual(again.account_id, principal.account_id)
        self.assertEqual(again.workspace_id, principal.workspace_id)
        self.assertEqual(self.verifier.tokens, ["eyJhbGciOi.x.y", "eyJhbGciOi.other.token"])

    async def test_token_keeps_the_stored_email_when_a_token_omits_it(self) -> None:
        use_case = self._use_case()
        await use_case.from_token_claims({"sub": "user-123", "email": "a@b.test", "role": "authenticated"})

        principal = await use_case.from_token_claims({"sub": "user-123", "role": "authenticated"})

        self.assertEqual(principal.email, "a@b.test")

    async def test_unconfigured_directory_behaves_like_before_accounts(self) -> None:
        use_case = self._use_case(accounts=InMemoryAccountDirectory(enabled=False))

        principal = await use_case.resolve(authorization="Bearer eyJ.x.y")

        self.assertEqual(principal.subject, "user:user-123")
        self.assertIs(principal.method, AuthMethod.TOKEN)
        self.assertIsNone(principal.account_id)
        self.assertIsNone(principal.workspace_id)
        self.assertEqual(principal.owner_id, "user:user-123")

    async def test_token_that_fails_verification_is_a_generic_401(self) -> None:
        self.verifier.error = ValueError("signature mismatch for eyJ.secret.token")
        with self.assertRaises(AuthenticationError) as caught:
            await self._use_case().resolve(authorization="Bearer eyJ.secret.token")
        self.assertEqual(str(caught.exception), "Invalid access token.")

    async def test_unconfigured_identity_provider_is_its_own_error(self) -> None:
        self.verifier.error = AuthNotConfiguredError("Authentication is not configured.")
        with self.assertRaises(AuthNotConfiguredError):
            await self._use_case().resolve(authorization="Bearer eyJ.x.y")

    async def test_token_without_a_subject_is_rejected(self) -> None:
        for claims in ({"email": "a@b.test"}, {"sub": "  "}, {"sub": None}):
            with self.subTest(claims=claims), self.assertRaises(AuthenticationError):
                await self._use_case().from_token_claims(claims)

    async def test_only_a_real_signed_in_user_is_accepted(self) -> None:
        rejected = (
            {"sub": "user-123"},
            {"sub": "user-123", "role": "anon"},
            {"sub": "user-123", "role": "service_role"},
            {"sub": "user-123", "role": "authenticated", "is_anonymous": True},
        )
        for claims in rejected:
            with self.subTest(claims=claims), self.assertRaises(AuthenticationError):
                await self._use_case().from_token_claims(claims)
        principal = await self._use_case().from_token_claims(
            {"sub": "user-123", "role": "authenticated", "is_anonymous": False}
        )
        self.assertIs(principal.method, AuthMethod.TOKEN)
        # A rejected anonymous sign-in never created an account.
        self.assertEqual(len(self.accounts._accounts), 1)

    async def test_the_bearer_scheme_is_case_insensitive(self) -> None:
        for header in ("bearer eyJ.x.y", "BEARER eyJ.x.y", "Bearer eyJ.x.y"):
            with self.subTest(header=header):
                principal = await self._use_case().resolve(authorization=header)
                self.assertIs(principal.method, AuthMethod.TOKEN)
        secret, _, _ = await self._issue_key()
        principal = await self._use_case().resolve(authorization=f"bearer {secret}")
        self.assertIs(principal.method, AuthMethod.API_KEY)
        anon = await self._use_case().resolve(authorization="Basic dXNlcjpwYXNz", client_id=CLIENT_ID)
        self.assertIs(anon.method, AuthMethod.ANONYMOUS)

    # -- API key ---------------------------------------------------------

    async def test_vl_live_bearer_routes_to_the_key_lookup_not_the_verifier(self) -> None:
        secret, account_id, workspace_id = await self._issue_key()

        principal = await self._use_case().resolve(authorization=f"Bearer {secret}")

        self.assertTrue(principal.subject.startswith("key:"))
        self.assertIs(principal.method, AuthMethod.API_KEY)
        self.assertTrue(principal.authenticated)
        self.assertEqual(principal.workspace_id, workspace_id)
        # The owning account, so quota is per person, not per key.
        self.assertEqual(principal.account_id, account_id)
        self.assertEqual(self.verifier.tokens, [])

    async def test_x_api_key_header_works_and_wins_over_a_bearer(self) -> None:
        secret, _, _ = await self._issue_key()

        principal = await self._use_case().resolve(authorization="Bearer eyJ.x.y", api_key=f"  {secret} ")

        self.assertIs(principal.method, AuthMethod.API_KEY)
        self.assertEqual(self.verifier.tokens, [])

    async def test_unknown_and_revoked_keys_are_rejected(self) -> None:
        with self.assertRaises(AuthenticationError):
            await self._use_case().resolve(api_key="vl_live_not-a-real-key")

        secret, _, workspace_id = await self._issue_key()
        key = (await self.api_keys.list_for_workspace(workspace_id))[0]
        await self.api_keys.revoke(workspace_id, key.key_id)
        with self.assertRaises(AuthenticationError):
            await self._use_case().resolve(authorization=f"Bearer {secret}")

    async def test_key_whose_workspace_is_gone_is_rejected(self) -> None:
        created = await self.api_keys.issue("ws-gone", "ci", ["runs:read"], max_active=10)
        with self.assertRaises(AuthenticationError):
            await self._use_case().resolve(api_key=created.secret)

    async def test_keys_do_not_work_without_an_account_store(self) -> None:
        use_case = self._use_case(
            accounts=InMemoryAccountDirectory(enabled=False), api_keys=InMemoryApiKeyRepository(enabled=False)
        )
        with self.assertRaises(AuthenticationError):
            await use_case.resolve(api_key="vl_live_anything")


if __name__ == "__main__":
    unittest.main()
