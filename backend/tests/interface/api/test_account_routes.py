"""`/api/me` and `/api/keys`: who may call what, end to end through FastAPI.

The container's identity use cases are swapped for ones built over fresh
in-memory adapters and a fake token verifier, so a bearer token is whatever
the test says it is and nothing touches a real identity provider."""

import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from app.application.create_api_key import CreateApiKeyUseCase
from app.application.entitlements import EntitlementResolver
from app.application.get_account import GetAccountUseCase
from app.application.identify_caller import IdentifyCallerUseCase
from app.application.list_api_keys import ListApiKeysUseCase
from app.application.revoke_api_key import RevokeApiKeyUseCase
from app.container import container
from app.domain.errors import AuthNotConfiguredError
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
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
