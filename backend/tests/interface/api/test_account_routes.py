"""The account, billing, key and library routes on a bare deployment: no
database, no Stripe, no identity provider. Every one must either work for an
anonymous caller or refuse cleanly, because that is the configuration every
fresh checkout runs with."""

import unittest

from starlette.testclient import TestClient

from app.container import container
from app.interface.api.app import app

CLIENT_HEADERS = {"X-Client-ID": "client-0123456789abcdef"}


class AccountRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_me_describes_an_anonymous_caller_and_the_deployment_limits(self) -> None:
        response = self.client.get("/api/me", headers=CLIENT_HEADERS)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["subject"], "client:client-0123456789abcdef")
        self.assertEqual(body["method"], "anonymous")
        self.assertIsNone(body["workspace"])
        self.assertEqual(body["usage"]["plan"], "free")
        self.assertEqual(body["usage"]["max_duration_seconds"], container.settings.max_duration_seconds)
        self.assertFalse(body["billing_enabled"])
        self.assertFalse(body["accounts_enabled"])

    def test_me_without_any_credential_is_a_bad_request(self) -> None:
        response = self.client.get("/api/me")
        self.assertEqual(response.status_code, 400)

    def test_library_search_works_for_anonymous_callers(self) -> None:
        response = self.client.get("/api/library", params={"query": "bread"}, headers=CLIENT_HEADERS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"runs": [], "query": "bread", "limit": 20, "offset": 0})

    def test_library_rejects_out_of_range_paging(self) -> None:
        response = self.client.get("/api/library", params={"limit": 500}, headers=CLIENT_HEADERS)
        self.assertEqual(response.status_code, 422)

    def test_account_management_refuses_anonymous_callers(self) -> None:
        for method, path, body in (
            ("GET", "/api/keys", None),
            ("POST", "/api/keys", {"name": "x"}),
            ("DELETE", "/api/keys/key-1", None),
            ("POST", "/api/billing/checkout", {"plan": "pro"}),
            ("POST", "/api/billing/portal", None),
        ):
            response = self.client.request(method, path, json=body, headers=CLIENT_HEADERS)
            self.assertEqual(response.status_code, 401, f"{method} {path}")

    def test_api_key_bearer_is_rejected_when_no_keys_exist(self) -> None:
        response = self.client.get("/api/me", headers={"Authorization": "Bearer vl_live_abcdef01_nope"})
        self.assertEqual(response.status_code, 401)

        response = self.client.get("/api/me", headers={"X-Api-Key": "vl_live_abcdef01_nope"})
        self.assertEqual(response.status_code, 401)

    def test_stripe_webhook_is_unavailable_until_configured(self) -> None:
        response = self.client.post(
            "/api/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"}
        )
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
