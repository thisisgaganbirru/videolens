import unittest
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from app.application.entitlements import EntitlementResolver
from app.container import container
from app.domain.errors import LongRunInProgressError
from app.interface.api.app import app

HEADERS = {"X-Client-ID": "test-client-0123456789", "X-Gemini-Api-Key": "user-key"}
FORM = {"url": "https://x.test/v.mp4", "accept_terms": "true"}


class LimitsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_exact_contract_from_settings(self) -> None:
        settings = container.settings
        response = self.client.get("/api/limits")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "standard": {
                    "max_duration_seconds": settings.max_duration_seconds,
                    "max_file_size_mb": settings.max_file_size_mb,
                },
                "signed_in_byok": {
                    "max_duration_seconds": max(
                        settings.signed_in_byok_max_duration_seconds, settings.max_duration_seconds
                    ),
                    "max_file_size_mb": max(settings.signed_in_byok_max_file_size_mb, settings.max_file_size_mb),
                },
                # PAID_* default to the signed-in BYOK numbers.
                "paid": {
                    "max_duration_seconds": container.entitlements.paid.max_duration_seconds,
                    "max_file_size_mb": container.entitlements.paid.max_file_size_mb,
                },
            },
        )
        # Briefly cacheable: its own header wins over the no-store default.
        self.assertEqual(response.headers["cache-control"], "public, max-age=300")

    def test_defaults(self) -> None:
        resolver = EntitlementResolver(
            max_duration_seconds=180,
            max_file_size_mb=200,
            signed_in_byok_max_duration_seconds=600,
            signed_in_byok_max_file_size_mb=500,
        )
        with patch.object(container, "entitlements", resolver):
            body = self.client.get("/api/limits").json()
        self.assertEqual(
            body,
            {
                "standard": {"max_duration_seconds": 180, "max_file_size_mb": 200},
                "signed_in_byok": {"max_duration_seconds": 600, "max_file_size_mb": 500},
                "paid": {"max_duration_seconds": 600, "max_file_size_mb": 500},
            },
        )

    def test_paid_numbers_of_their_own(self) -> None:
        resolver = EntitlementResolver(
            max_duration_seconds=180,
            max_file_size_mb=200,
            signed_in_byok_max_duration_seconds=600,
            signed_in_byok_max_file_size_mb=500,
            paid_max_duration_seconds=900,
            paid_max_file_size_mb=700,
        )
        with patch.object(container, "entitlements", resolver):
            body = self.client.get("/api/limits").json()
        self.assertEqual(body["paid"], {"max_duration_seconds": 900, "max_file_size_mb": 700})

    def test_a_smaller_bigger_tier_reports_the_standard_numbers(self) -> None:
        resolver = EntitlementResolver(
            max_duration_seconds=180,
            max_file_size_mb=200,
            signed_in_byok_max_duration_seconds=100,
            signed_in_byok_max_file_size_mb=50,
        )
        with patch.object(container, "entitlements", resolver):
            body = self.client.get("/api/limits").json()
        self.assertEqual(body["signed_in_byok"], {"max_duration_seconds": 180, "max_file_size_mb": 200})

    def test_needs_no_credentials(self) -> None:
        # No X-Client-ID, no bearer: still 200.
        self.assertEqual(self.client.get("/api/limits").status_code, 200)


class LongRunInProgressResponseTests(unittest.TestCase):
    def test_429_with_a_code(self) -> None:
        client = TestClient(app)
        with patch.object(
            container.create_run_use_case, "execute", AsyncMock(side_effect=LongRunInProgressError())
        ):
            response = client.post("/api/runs", headers=HEADERS, data=FORM)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            response.json(),
            {
                "detail": "You already have a long video processing. Wait for it to finish.",
                "code": "long_run_in_progress",
            },
        )


if __name__ == "__main__":
    unittest.main()
