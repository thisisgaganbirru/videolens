"""A held account (deleted, inside its 30-day hold) is refused on every
authenticated route family, not only on `/api/me` and `/api/keys`: 410
`account_pending_deletion` for its bearer token, 401 for its API keys, and
`POST /api/me/restore` is the one route that still answers
(docs/backend/auth.md, "A held account").

The gate is `IdentifyCallerUseCase`, which every principal dependency calls
before the route body runs, so the other use cases are never reached and
are left as the container built them."""

import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from app.application.create_api_key import CreateApiKeyUseCase
from app.application.delete_account import DeleteAccountUseCase
from app.application.identify_caller import IdentifyCallerUseCase
from app.application.restore_account import RestoreAccountUseCase
from app.container import container
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_deleter import InMemoryAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
from app.infrastructure.persistence.run_repository import RunStore
from app.interface.api.app import app

TOKEN = {"Authorization": "Bearer eyJhbGciOi.payload.signature"}

# (method, path, keyword arguments) for every route that resolves a caller.
ROUTES = (
    ("post", "/api/runs", {"data": {"url": "https://example.com/v.mp4", "accept_terms": "true"}}),
    ("get", "/api/runs", {}),
    ("get", "/api/runs/run-1", {}),
    ("get", "/api/free-runs", {}),
    ("get", "/api/billing", {}),
    ("post", "/api/billing/checkout", {"json": {"interval": "month"}}),
    ("post", "/api/billing/portal", {}),
    ("get", "/api/history", {}),
    ("get", "/api/history/run-1", {}),
    ("delete", "/api/history/run-1", {}),
    ("delete", "/api/history", {}),
    ("get", "/api/keys", {}),
    ("post", "/api/keys", {"json": {"name": "again"}}),
    ("delete", "/api/keys/key-1", {}),
    ("get", "/api/me", {}),
    ("delete", "/api/me", {}),
)


class FakeTokenVerifier:
    def __init__(self, claims: dict) -> None:
        self.claims = claims

    def decode(self, token: str) -> dict:
        return dict(self.claims)


class HeldAccountGateTests(unittest.TestCase):
    def setUp(self) -> None:
        accounts = InMemoryAccountDirectory()
        keys = InMemoryApiKeyRepository()
        deleter = InMemoryAccountDeleter(Settings(_env_file=None), accounts=accounts, api_keys=keys)
        replacements = {
            "identify_caller_use_case": IdentifyCallerUseCase(
                accounts=accounts,
                api_keys=keys,
                verifier=FakeTokenVerifier({"sub": "user-123", "email": "a@b.test", "role": "authenticated"}),
                allow_anonymous=True,
            ),
            "create_api_key_use_case": CreateApiKeyUseCase(api_keys=keys, accounts=accounts, max_active=2),
            "delete_account_use_case": DeleteAccountUseCase(
                accounts=accounts, deleter=deleter, api_keys=keys, runs=RunStore(Settings(_env_file=None))
            ),
            "restore_account_use_case": RestoreAccountUseCase(deleter=deleter),
        }
        patcher = patch.multiple(container, **replacements)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)
        created = self.client.post("/api/keys", headers=TOKEN, json={"name": "ci"})
        self.assertEqual(created.status_code, 201, created.text)
        self.secret = created.json()["secret"]
        held = self.client.delete("/api/me", headers=TOKEN)
        self.assertEqual(held.status_code, 200, held.text)
        self.purge_at = held.json()["purge_at"]

    def _call(self, method: str, path: str, headers: dict, kwargs: dict):
        return self.client.request(method.upper(), path, headers=headers, **kwargs)

    def test_every_route_answers_410_to_the_held_accounts_token(self) -> None:
        for method, path, kwargs in ROUTES:
            with self.subTest(method=method, path=path):
                response = self._call(method, path, TOKEN, kwargs)
                self.assertEqual(response.status_code, 410, response.text)
                self.assertEqual(response.json()["code"], "account_pending_deletion")
                self.assertEqual(response.json()["purge_at"], self.purge_at)

    def test_every_route_answers_401_to_the_held_accounts_api_key(self) -> None:
        # Never 410: an API key must not reveal that its account is held.
        for header in ("X-Api-Key", "Authorization"):
            value = self.secret if header == "X-Api-Key" else f"Bearer {self.secret}"
            for method, path, kwargs in ROUTES:
                with self.subTest(header=header, method=method, path=path):
                    response = self._call(method, path, {header: value}, kwargs)
                    self.assertEqual(response.status_code, 401, response.text)
                    self.assertNotIn("code", response.json())

    def test_restore_is_the_one_route_that_still_answers(self) -> None:
        restored = self.client.post("/api/me/restore", headers=TOKEN)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json(), {"restored": True})
        # And with the hold lifted the account and its key work again.
        self.assertEqual(self.client.get("/api/me", headers=TOKEN).status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers={"X-Api-Key": self.secret}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
