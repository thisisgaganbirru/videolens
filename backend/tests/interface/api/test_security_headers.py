import unittest

from starlette.testclient import TestClient

from app.interface.api.app import app
from app.interface.api.security_headers import SECURITY_HEADERS


class SecurityHeaderTests(unittest.TestCase):
    """Every API answer carries the hardening set, whichever layer produced
    it: a route, a 404 from the router, a CORS preflight."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def _assert_all_present(self, response) -> None:
        for name, value in SECURITY_HEADERS:
            self.assertEqual(response.headers.get(name), value, name)

    def test_on_a_normal_route(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self._assert_all_present(response)

    def test_on_a_404(self) -> None:
        self._assert_all_present(self.client.get("/api/nope"))

    def test_on_a_cors_preflight(self) -> None:
        response = self.client.options(
            "/api/runs",
            headers={
                "Origin": "https://localhost",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-client-id",
            },
        )
        self.assertEqual(response.status_code, 200)
        self._assert_all_present(response)

    def test_run_answers_are_never_stored(self) -> None:
        response = self.client.get("/api/runs/does-not-exist", headers={"X-Client-ID": "abcdefghijklmnop"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
