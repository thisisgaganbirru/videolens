import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from app.application.create_run import CreateRunUseCase
from app.application.get_free_runs import GetFreeRunsUseCase
from app.application.identify_caller import IdentifyCallerUseCase
from app.container import container
from app.domain.errors import AuthNotConfiguredError
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.account_free_runs import InMemoryAccountFreeRuns
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
from app.interface.api.app import app

HEADERS = {"X-Client-ID": "test-client-0123456789"}
FORM = {"url": "https://x.test/v.mp4", "accept_terms": "true"}


class FreeRunsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_issues_a_token_when_none_is_sent(self) -> None:
        response = self.client.get("/api/free-runs")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body), {"device_token", "enabled", "scope", "period", "limit", "used", "remaining", "resets_at"}
        )
        self.assertEqual((body["scope"], body["period"]), ("device", "day"))
        self.assertIsNotNone(container.device_tokens.verify(body["device_token"]))
        self.assertTrue(body["resets_at"].endswith("Z") or body["resets_at"].endswith("+00:00"))

    def test_keeps_a_genuine_token_and_never_consumes(self) -> None:
        token = self.client.get("/api/free-runs").json()["device_token"]
        for _ in range(3):
            body = self.client.get("/api/free-runs", headers={"X-Device-Token": token}).json()
        self.assertEqual(body["device_token"], token)
        self.assertEqual(body["used"], 0)
        self.assertEqual(body["remaining"], body["limit"])

    def test_replaces_a_forged_token(self) -> None:
        body = self.client.get("/api/free-runs", headers={"X-Device-Token": "made.up"}).json()
        self.assertNotEqual(body["device_token"], "made.up")
        self.assertIsNotNone(container.device_tokens.verify(body["device_token"]))

    def test_reports_disabled_when_free_runs_are_off(self) -> None:
        with patch.object(container.settings, "free_runs_per_device", 0):
            body = self.client.get("/api/free-runs").json()
        self.assertFalse(body["enabled"])
        self.assertEqual((body["limit"], body["used"], body["remaining"]), (0, 0, 0))
        self.assertTrue(body["device_token"])


class CreateRunFreeRunErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_missing_device_token_is_401_with_a_code(self) -> None:
        response = self.client.post("/api/runs", headers=HEADERS, data=FORM)

        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertEqual(body["code"], "device_token_invalid")
        self.assertTrue(body["detail"])

    def test_used_up_free_runs_is_402_with_the_device_numbers(self) -> None:
        token = self.client.get("/api/free-runs").json()["device_token"]
        with patch.object(container.free_runs, "try_consume", AsyncMock(return_value=None)):
            response = self.client.post(
                "/api/runs", headers={**HEADERS, "X-Device-Token": token}, data=FORM
            )

        self.assertEqual(response.status_code, 402)
        self.assertEqual(
            response.json(),
            {
                "detail": "You have used your free runs. Add your own Gemini key to keep going.",
                "code": "free_runs_used",
                "scope": "device",
                "period": "day",
                "limit": container.settings.free_runs_per_device,
                "used": 0,
            },
        )

    def test_cors_allows_the_device_token_header(self) -> None:
        response = self.client.options(
            "/api/free-runs",
            headers={
                "Origin": "https://localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-device-token",
            },
        )
        self.assertEqual(response.status_code, 200)


class _Verifier:
    """Fixed claims, or `error` raised (the application fakes are not
    importable from here under `unittest discover`)."""

    def __init__(self, claims: dict, error: Exception | None = None) -> None:
        self.claims = claims
        self.error = error

    def decode(self, token: str) -> dict:
        if self.error is not None:
            raise self.error
        return dict(self.claims)


TOKEN = {"Authorization": "Bearer eyJhbGciOi.payload.signature"}


class AccountFreeRunRouteTests(unittest.TestCase):
    """Signed-in free runs end to end: the container's identity, free-run
    and create-run use cases are rebuilt over fresh in-memory adapters, so a
    bearer token is whatever the test says and the counts start at zero."""

    def setUp(self) -> None:
        self.verifier = _Verifier({"sub": "user-123", "email": "a@b.test", "role": "authenticated"})
        self.accounts = InMemoryAccountDirectory()
        self.keys = InMemoryApiKeyRepository()
        self.account_runs = InMemoryAccountFreeRuns(
            Settings(_env_file=None, gemini_api_key="k", free_runs_per_account_daily=10)
        )
        replacements = {
            "identify_caller_use_case": IdentifyCallerUseCase(
                accounts=self.accounts, api_keys=self.keys, verifier=self.verifier, allow_anonymous=True
            ),
            "get_free_runs_use_case": GetFreeRunsUseCase(
                free_runs=container.free_runs,
                device_tokens=container.device_tokens,
                account_free_runs=self.account_runs,
            ),
            "create_run_use_case": CreateRunUseCase(
                runs=container.run_repository,
                media=container.media,
                storage=container.object_store,
                queue=container.job_queue,
                spend_cap=container.spend_cap,
                free_runs=container.free_runs,
                device_tokens=container.device_tokens,
                distributed=False,
                account_free_runs=self.account_runs,
            ),
        }
        for name, value in replacements.items():
            patcher = patch.object(container, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def _account_id(self) -> str:
        return self.accounts.account_id_for("user-123")

    def test_a_signed_in_caller_gets_the_account_standing(self) -> None:
        response = self.client.get("/api/free-runs", headers=TOKEN)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # Signed in also carries the plan (docs/backend/billing.md).
        self.assertEqual(
            set(body),
            {
                "device_token",
                "enabled",
                "scope",
                "period",
                "limit",
                "used",
                "remaining",
                "resets_at",
                "plan",
                "overage",
            },
        )
        self.assertEqual(
            (body["enabled"], body["scope"], body["period"], body["limit"], body["used"], body["remaining"]),
            (True, "account", "day", 10, 0, 10),
        )
        self.assertEqual((body["plan"], body["overage"]), ("free", False))
        # Still issued, so the person keeps a device token after signing out.
        self.assertIsNotNone(container.device_tokens.verify(body["device_token"]))
        # Daily since 2026-11-14: the next UTC midnight.
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        self.assertRegex(body["resets_at"], rf"^{tomorrow}T00:00:00(Z|\+00:00)$")

    def test_a_genuine_device_token_is_echoed_for_a_signed_in_caller(self) -> None:
        token = self.client.get("/api/free-runs").json()["device_token"]
        body = self.client.get("/api/free-runs", headers={**TOKEN, "X-Device-Token": token}).json()
        self.assertEqual(body["device_token"], token)
        self.assertEqual(body["scope"], "account")

    def test_used_reflects_the_account_counter(self) -> None:
        self.client.get("/api/free-runs", headers=TOKEN)  # first sight creates the account
        account_id = self._account_id()
        import asyncio

        for _ in range(4):
            asyncio.run(self.account_runs.try_consume(account_id))
        body = self.client.get("/api/free-runs", headers=TOKEN).json()
        self.assertEqual((body["used"], body["remaining"]), (4, 6))

    def test_an_invalid_bearer_is_401_like_api_me(self) -> None:
        self.verifier.error = ValueError("bad signature")
        for path in ("/api/free-runs", "/api/me"):
            response = self.client.get(path, headers=TOKEN)
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(response.headers.get("www-authenticate"), "Bearer")

    def test_an_unknown_api_key_is_401(self) -> None:
        response = self.client.get("/api/free-runs", headers={"Authorization": "Bearer vl_live_" + "x" * 43})
        self.assertEqual(response.status_code, 401)

    def test_auth_not_configured_is_503_like_api_me(self) -> None:
        self.verifier.error = AuthNotConfiguredError("Sign-in is not configured on this server.")
        self.assertEqual(self.client.get("/api/free-runs", headers=TOKEN).status_code, 503)
        self.assertEqual(self.client.get("/api/me", headers=TOKEN).status_code, 503)

    def test_an_empty_bearer_is_treated_as_anonymous(self) -> None:
        body = self.client.get("/api/free-runs", headers={"Authorization": "Bearer "}).json()
        self.assertEqual(body["scope"], "device")

    def test_disabled_account_allowance_reports_the_device_standing(self) -> None:
        with patch.object(self.account_runs._settings, "free_runs_per_account_daily", 0):
            body = self.client.get("/api/free-runs", headers=TOKEN).json()
        self.assertEqual(body["scope"], "device")
        self.assertEqual(body["limit"], container.settings.free_runs_per_device)

    def test_used_up_account_runs_is_402_with_the_account_numbers(self) -> None:
        with patch.object(self.account_runs, "try_consume", AsyncMock(return_value=None)):
            response = self.client.post("/api/runs", headers=TOKEN, data=FORM)

        self.assertEqual(response.status_code, 402, response.text)
        self.assertEqual(
            response.json(),
            {
                "detail": (
                    "You have used today's free runs. Add your own Gemini key to keep going, or come back tomorrow."
                ),
                "code": "free_runs_used",
                "scope": "account",
                "period": "day",
                "limit": 10,
                "used": 0,
            },
        )

    def test_a_signed_in_run_needs_no_device_token(self) -> None:
        # Refused at the account counter (402), not for a missing device
        # token (401): the device rule is not consulted.
        with patch.object(self.account_runs, "try_consume", AsyncMock(return_value=None)):
            response = self.client.post("/api/runs", headers=TOKEN, data=FORM)
        self.assertNotEqual(response.json().get("code"), "device_token_invalid")

    def test_cors_allows_authorization_on_free_runs(self) -> None:
        response = self.client.options(
            "/api/free-runs",
            headers={
                "Origin": "https://localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization, x-device-token",
            },
        )
        self.assertEqual(response.status_code, 200)
        allowed = response.headers.get("access-control-allow-headers", "").lower()
        self.assertIn("authorization", allowed)
        self.assertIn("x-device-token", allowed)


if __name__ == "__main__":
    unittest.main()
