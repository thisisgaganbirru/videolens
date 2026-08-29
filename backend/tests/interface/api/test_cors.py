import unittest

from starlette.testclient import TestClient

from app.interface.api.app import app


class CorsPreflightTests(unittest.TestCase):
    """`CORSMiddleware` answers a preflight from an unlisted origin with a bare
    400. In the browser that surfaces as a rejected `fetch`, which
    `frontend/infrastructure/runsGateway.ts` cannot tell apart from an offline
    server - so a CORS gap reaches the user as "Can't reach the server."
    These assert the wiring in `app.py` end to end, not just the settings."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def _preflight(self, origin: str):
        return self.client.options(
            "/api/runs",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-client-id",
            },
        )

    def test_allows_the_capacitor_android_webview_origin(self) -> None:
        response = self._preflight("https://localhost")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "https://localhost")

    def test_rejects_an_unrelated_origin(self) -> None:
        response = self._preflight("https://evil.example.com")

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
