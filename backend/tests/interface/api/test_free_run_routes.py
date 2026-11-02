import unittest
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from app.container import container
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
            set(body), {"device_token", "enabled", "limit", "used", "remaining", "resets_at"}
        )
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


if __name__ == "__main__":
    unittest.main()
