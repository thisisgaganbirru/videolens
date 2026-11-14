"""`/api/me` and `/api/keys`: who may call what, end to end through FastAPI.

The container's identity use cases are swapped for ones built over fresh
in-memory adapters and a fake token verifier, so a bearer token is whatever
the test says it is and nothing touches a real identity provider."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from starlette.testclient import TestClient

from app.application.cleanup import AccountCleanupUseCase
from app.application.create_api_key import CreateApiKeyUseCase
from app.application.delete_account import DeleteAccountUseCase
from app.application.entitlements import EntitlementResolver
from app.application.get_account import GetAccountUseCase
from app.application.identify_caller import IdentifyCallerUseCase
from app.application.list_api_keys import ListApiKeysUseCase
from app.application.restore_account import RestoreAccountUseCase
from app.application.revoke_api_key import RevokeApiKeyUseCase
from app.container import container
from app.domain.errors import AuthNotConfiguredError
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_deleter import InMemoryAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
from app.infrastructure.persistence.run_repository import RunStore
from app.interface.api.app import app



class FakeTokenVerifier:
    """Fixed claims, or `error` raised. (`tests/application/fakes.py` has the
    same one; `unittest discover -s tests` cannot import across packages.)"""

    def __init__(self, claims: dict, error: Exception | None = None) -> None:
        self.claims = claims
        self.error = error

    def decode(self, token: str) -> dict:
        if self.error is not None:
            raise self.error
        return dict(self.claims)

ANON = {"X-Client-ID": "test-client-0123456789"}
TOKEN = {"Authorization": "Bearer eyJhbGciOi.payload.signature"}


class AccountRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = FakeTokenVerifier({"sub": "user-123", "email": "a@b.test", "role": "authenticated"})
        accounts = InMemoryAccountDirectory()
        keys = InMemoryApiKeyRepository()
        self.accounts = accounts
        self.runs = RunStore(Settings(_env_file=None))
        deleter = InMemoryAccountDeleter(Settings(_env_file=None), accounts=accounts, api_keys=keys)
        replacements = {
            "identify_caller_use_case": IdentifyCallerUseCase(
                accounts=accounts, api_keys=keys, verifier=self.verifier, allow_anonymous=True
            ),
            "get_account_use_case": GetAccountUseCase(
                accounts=accounts, entitlements=EntitlementResolver(max_duration_seconds=180, max_file_size_mb=200)
            ),
            "create_api_key_use_case": CreateApiKeyUseCase(api_keys=keys, accounts=accounts, max_active=2),
            "list_api_keys_use_case": ListApiKeysUseCase(api_keys=keys, accounts=accounts),
            "revoke_api_key_use_case": RevokeApiKeyUseCase(api_keys=keys, accounts=accounts),
            "delete_account_use_case": DeleteAccountUseCase(
                accounts=accounts, deleter=deleter, api_keys=keys, runs=self.runs
            ),
            "restore_account_use_case": RestoreAccountUseCase(deleter=deleter),
        }
        for name, value in replacements.items():
            patcher = patch.object(container, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def _new_key(self, name: str = "ci") -> dict:
        response = self.client.post("/api/keys", headers=TOKEN, json={"name": name})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    # -- /api/me ---------------------------------------------------------

    def test_me_is_401_for_anonymous_callers(self) -> None:
        response = self.client.get("/api/me", headers=ANON)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("www-authenticate"), "Bearer")

    def test_me_describes_a_signed_in_person(self) -> None:
        response = self.client.get("/api/me", headers=TOKEN)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["subject"], "user:user-123")
        self.assertEqual(body["method"], "token")
        self.assertEqual(body["email"], "a@b.test")
        self.assertEqual(body["workspace"]["name"], "Personal")
        self.assertEqual(body["entitlement"]["plan"], "free")
        self.assertEqual(body["entitlement"]["max_duration_seconds"], 180)
        self.assertTrue(body["entitlement"]["api_access"])
        self.assertTrue(body["accounts_enabled"])

    def test_me_works_with_an_api_key_in_either_header(self) -> None:
        secret = self._new_key()["secret"]
        person = self.client.get("/api/me", headers=TOKEN).json()

        for headers in ({"X-Api-Key": secret}, {"Authorization": f"Bearer {secret}"}):
            with self.subTest(header=next(iter(headers))):
                response = self.client.get("/api/me", headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["method"], "api_key")
                self.assertEqual(body["account_id"], person["account_id"])
                self.assertEqual(body["workspace"]["workspace_id"], person["workspace"]["workspace_id"])

    def test_bad_token_is_a_generic_401(self) -> None:
        self.verifier.error = ValueError("bad signature")
        response = self.client.get("/api/me", headers=TOKEN)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("signature", response.text)

    def test_unconfigured_sign_in_is_503(self) -> None:
        self.verifier.error = AuthNotConfiguredError("Authentication is not configured.")
        response = self.client.get("/api/me", headers=TOKEN)
        self.assertEqual(response.status_code, 503)

    # -- /api/keys -------------------------------------------------------

    def test_key_routes_are_401_for_anonymous_callers(self) -> None:
        for method, path in (("get", "/api/keys"), ("post", "/api/keys"), ("delete", "/api/keys/k1")):
            with self.subTest(method=method):
                kwargs = {"json": {"name": "x"}} if method == "post" else {}
                response = getattr(self.client, method)(path, headers=ANON, **kwargs)
                self.assertEqual(response.status_code, 401)

    def test_key_routes_are_403_for_an_api_key(self) -> None:
        secret = self._new_key()["secret"]
        for method, path in (("get", "/api/keys"), ("post", "/api/keys"), ("delete", "/api/keys/k1")):
            with self.subTest(method=method):
                kwargs = {"json": {"name": "x"}} if method == "post" else {}
                response = getattr(self.client, method)(path, headers={"X-Api-Key": secret}, **kwargs)
                self.assertEqual(response.status_code, 403)

    def test_a_signed_in_person_creates_lists_and_revokes(self) -> None:
        created = self._new_key("laptop")
        self.assertTrue(created["secret"].startswith("vl_live_"))
        self.assertTrue(created["secret"].startswith(created["prefix"]))
        self.assertEqual(created["name"], "laptop")

        listed = self.client.get("/api/keys", headers=TOKEN)
        self.assertEqual(listed.status_code, 200)
        keys = listed.json()["keys"]
        self.assertEqual([key["key_id"] for key in keys], [created["key_id"]])
        self.assertNotIn("secret", keys[0])

        revoked = self.client.delete(f"/api/keys/{created['key_id']}", headers=TOKEN)
        self.assertEqual(revoked.status_code, 204)
        self.assertEqual(self.client.get("/api/me", headers={"X-Api-Key": created["secret"]}).status_code, 401)
        self.assertEqual(self.client.delete(f"/api/keys/{created['key_id']}", headers=TOKEN).status_code, 404)

    def test_the_cap_is_409(self) -> None:
        self._new_key("a")
        self._new_key("b")
        response = self.client.post("/api/keys", headers=TOKEN, json={"name": "c"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("at most 2", response.json()["detail"])

    # -- DELETE /api/me --------------------------------------------------

    def test_delete_me_is_401_for_anonymous_callers(self) -> None:
        response = self.client.delete("/api/me", headers=ANON)
        self.assertEqual(response.status_code, 401)

    def test_delete_me_is_403_for_an_api_key(self) -> None:
        secret = self._new_key()["secret"]
        for headers in ({"X-Api-Key": secret}, {"Authorization": f"Bearer {secret}"}):
            with self.subTest(header=next(iter(headers))):
                self.assertEqual(self.client.delete("/api/me", headers=headers).status_code, 403)
        # The key still works: nothing was deleted.
        self.assertEqual(self.client.get("/api/me", headers={"X-Api-Key": secret}).status_code, 200)

    def test_delete_me_holds_the_account_and_blocks_it_at_once(self) -> None:
        secret = self._new_key()["secret"]
        before = self.client.get("/api/me", headers=TOKEN).json()

        response = self.client.delete("/api/me", headers=TOKEN)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "pending_deletion")
        purge_at = body["purge_at"]
        # Every account endpoint now answers 410 with the purge date...
        for method, path in (("get", "/api/me"), ("get", "/api/keys"), ("delete", "/api/me"), ("get", "/api/history")):
            with self.subTest(path=path, method=method):
                held = getattr(self.client, method)(path, headers=TOKEN)
                self.assertEqual(held.status_code, 410, held.text)
                self.assertEqual(held.json()["code"], "account_pending_deletion")
                self.assertEqual(held.json()["purge_at"], purge_at)
        # ...its API keys stop working, and no fresh account is created.
        self.assertEqual(self.client.get("/api/me", headers={"X-Api-Key": secret}).status_code, 401)
        self.assertEqual(self.accounts.account_id_for("user-123"), before["account_id"])

    def test_restore_brings_back_the_same_account_and_its_keys(self) -> None:
        secret = self._new_key()["secret"]
        before = self.client.get("/api/me", headers=TOKEN).json()
        self.client.delete("/api/me", headers=TOKEN)

        restored = self.client.post("/api/me/restore", headers=TOKEN)

        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json(), {"restored": True})
        after = self.client.get("/api/me", headers=TOKEN).json()
        self.assertEqual(after["account_id"], before["account_id"])
        self.assertEqual(self.client.get("/api/me", headers={"X-Api-Key": secret}).status_code, 200)
        # A repeat is harmless.
        self.assertEqual(self.client.post("/api/me/restore", headers=TOKEN).json(), {"restored": False})

    def test_restore_is_a_signed_in_session_only(self) -> None:
        secret = self._new_key()["secret"]
        self.assertEqual(self.client.post("/api/me/restore", headers=ANON).status_code, 401)
        self.assertEqual(self.client.post("/api/me/restore", headers={"X-Api-Key": secret}).status_code, 403)

    def test_restore_after_the_hold_is_410_window_closed(self) -> None:
        keys = InMemoryApiKeyRepository()
        deleter = InMemoryAccountDeleter(Settings(_env_file=None), accounts=self.accounts, api_keys=keys)
        replacements = {
            "delete_account_use_case": DeleteAccountUseCase(
                accounts=self.accounts, deleter=deleter, api_keys=keys, runs=self.runs, hold_days=0
            ),
            "restore_account_use_case": RestoreAccountUseCase(deleter=deleter),
        }
        with patch.multiple(container, **replacements):
            self.assertEqual(self.client.delete("/api/me", headers=TOKEN).status_code, 200)
            response = self.client.post("/api/me/restore", headers=TOKEN)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["code"], "restore_window_closed")

    def _with_a_real_identity_step(self, *, identity_fails_once: bool = False):
        """Rewire with an identity provider that forgets the user when the
        cleanup's identity step runs. Returns the provider's `gone` set and
        a function running the cleanup as if `days` had passed."""
        gone: set[str] = set()
        failures = [RuntimeError("auth.users unreachable")] if identity_fails_once else []

        class Users:
            async def exists(self, external_id: str) -> bool:
                return external_id not in gone

        users = Users()
        accounts = InMemoryAccountDirectory(users=users)
        keys = InMemoryApiKeyRepository()

        class Deleter(InMemoryAccountDeleter):
            async def delete_identity(self, external_id: str) -> bool:
                if failures:
                    raise failures.pop()
                gone.add(external_id)
                return True

        deleter = Deleter(Settings(_env_file=None), accounts=accounts, api_keys=keys)
        replacements = {
            "identify_caller_use_case": IdentifyCallerUseCase(
                accounts=accounts, api_keys=keys, verifier=self.verifier, allow_anonymous=True
            ),
            "create_api_key_use_case": CreateApiKeyUseCase(
                api_keys=keys, accounts=accounts, max_active=2, users=users
            ),
            "delete_account_use_case": DeleteAccountUseCase(
                accounts=accounts, deleter=deleter, api_keys=keys, runs=self.runs
            ),
        }
        patcher = patch.multiple(container, **replacements)
        patcher.start()
        self.addCleanup(patcher.stop)

        def cleanup_after(days: int):
            later = datetime.now(timezone.utc) + timedelta(days=days)
            return asyncio.run(AccountCleanupUseCase(deleter=deleter, clock=lambda: later).run())

        return gone, cleanup_after

    def test_the_cleanup_removes_a_held_account_for_good_after_the_hold(self) -> None:
        gone, cleanup_after = self._with_a_real_identity_step()
        self.assertEqual(self.client.delete("/api/me", headers=TOKEN).status_code, 200)

        self.assertEqual(cleanup_after(29).accounts_removed, 0)
        self.assertEqual(gone, set())
        self.assertEqual(cleanup_after(31).accounts_removed, 1)
        self.assertEqual(gone, {"user-123"})

        # The token still verifies (stateless), but it must not re-create the
        # account or mint a key nobody could revoke.
        self.assertEqual(self.client.delete("/api/me", headers=TOKEN).status_code, 401)
        self.assertEqual(self.client.get("/api/me", headers=TOKEN).status_code, 401)
        self.assertEqual(self.client.post("/api/keys", headers=TOKEN, json={"name": "x"}).status_code, 401)

    def test_an_identity_step_failure_is_retried_on_the_next_tick(self) -> None:
        gone, cleanup_after = self._with_a_real_identity_step(identity_fails_once=True)
        self.client.delete("/api/me", headers=TOKEN)

        with self.assertLogs("videolens", "ERROR"):
            report = cleanup_after(31)
        self.assertEqual((report.accounts_removed, report.accounts_skipped), (0, 1))
        self.assertEqual(gone, set())

        self.assertEqual(cleanup_after(31).accounts_removed, 1)
        self.assertEqual(gone, {"user-123"})
        self.assertEqual(cleanup_after(31).accounts_removed, 0)  # idempotent

    def test_delete_me_is_503_without_an_account_store(self) -> None:
        accounts = InMemoryAccountDirectory(enabled=False)
        keys = InMemoryApiKeyRepository(enabled=False)
        replacements = {
            "identify_caller_use_case": IdentifyCallerUseCase(
                accounts=accounts, api_keys=keys, verifier=self.verifier, allow_anonymous=True
            ),
            "delete_account_use_case": DeleteAccountUseCase(
                accounts=accounts,
                deleter=InMemoryAccountDeleter(Settings(_env_file=None), accounts=accounts, api_keys=keys),
                api_keys=keys,
                runs=self.runs,
            ),
        }
        with patch.multiple(container, **replacements):
            response = self.client.delete("/api/me", headers=TOKEN)
        self.assertEqual(response.status_code, 503)

    def test_a_failed_deletion_is_a_readable_500(self) -> None:
        class FailingDeleter:
            enabled = True

            async def schedule_deletion(self, external_id: str, *, now, purge_at):
                raise RuntimeError("relation api_keys does not exist")

        use_case = DeleteAccountUseCase(
            accounts=self.accounts, deleter=FailingDeleter(), api_keys=InMemoryApiKeyRepository(), runs=self.runs
        )
        with patch.object(container, "delete_account_use_case", use_case), self.assertLogs("videolens", "ERROR"):
            response = self.client.delete("/api/me", headers=TOKEN)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("relation", response.text)
        self.assertIn("try again", response.json()["detail"])

    def test_unknown_key_is_401(self) -> None:
        response = self.client.get("/api/me", headers={"X-Api-Key": "vl_live_nope"})
        self.assertEqual(response.status_code, 401)


class AccountCorsTests(unittest.TestCase):
    def test_preflight_allows_the_key_header_and_delete(self) -> None:
        response = TestClient(app).options(
            "/api/keys/k1",
            headers={
                "Origin": "https://localhost",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "authorization, x-api-key",
            },
        )
        self.assertEqual(response.status_code, 200)
        allowed = response.headers["access-control-allow-headers"].lower()
        self.assertIn("x-api-key", allowed)
        self.assertIn("authorization", allowed)
        self.assertIn("DELETE", response.headers["access-control-allow-methods"])


if __name__ == "__main__":
    unittest.main()
