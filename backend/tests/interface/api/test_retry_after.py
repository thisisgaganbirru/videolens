import time
import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from limits import parse
from slowapi import Limiter
from starlette.testclient import TestClient

from app.domain.errors import QuotaExceededError, RateLimitedError
from app.interface.api.app import _rate_limited, app
from app.interface.api.error_handlers import register_error_handlers, retry_after_headers
from app.interface.api.rate_limiter import retry_after_seconds


class RetryAfterHeaderTests(unittest.TestCase):
    """The frontend words a 429 from `Retry-After` ("Try again in about N
    minutes", infrastructure/runsGateway.ts). Domain errors carry the seconds;
    only the interface layer turns them into the header."""

    def _app_raising(self, exc: Exception) -> TestClient:
        probe = FastAPI()
        register_error_handlers(probe)

        @probe.get("/boom")
        async def boom() -> None:
            raise exc

        return TestClient(probe)

    def test_daily_cap_answers_503_with_retry_after(self) -> None:
        client = self._app_raising(QuotaExceededError("Limit reached.", retry_after_seconds=5400))
        response = client.get("/boom")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["retry-after"], "5400")
        self.assertEqual(response.json(), {"detail": "Limit reached."})

    def test_rate_limited_error_answers_429_with_retry_after(self) -> None:
        client = self._app_raising(RateLimitedError("Slow down.", retry_after_seconds=120))
        response = client.get("/boom")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "120")

    def test_no_header_when_the_wait_is_unknown(self) -> None:
        client = self._app_raising(QuotaExceededError("Limit reached."))
        self.assertNotIn("retry-after", client.get("/boom").headers)

    def test_ignores_nonsense_values(self) -> None:
        self.assertIsNone(retry_after_headers(RateLimitedError("x", retry_after_seconds=0)))
        self.assertIsNone(retry_after_headers(ValueError("no attribute at all")))


class RateLimitWindowTests(unittest.TestCase):
    """Seconds until slowapi's window frees, read from the limit the request
    just tripped (`request.state.view_rate_limit`)."""

    def setUp(self) -> None:
        self.limiter = Limiter(key_func=lambda request: "ip:test", storage_uri="memory://")
        self.item = parse("2/hour")
        self.args = ["ip:test", "create_run"]
        for _ in range(3):
            self.limiter.limiter.hit(self.item, *self.args)

    def _request(self, view_rate_limit):
        return SimpleNamespace(state=SimpleNamespace(view_rate_limit=view_rate_limit))

    def test_reports_the_rest_of_the_window(self) -> None:
        seconds = retry_after_seconds(self._request((self.item, self.args)), self.limiter)
        self.assertIsNotNone(seconds)
        self.assertGreater(seconds, 3500)
        self.assertLessEqual(seconds, 3601)

    def test_none_without_a_recorded_limit(self) -> None:
        self.assertIsNone(retry_after_seconds(self._request(None), self.limiter))
        self.assertIsNone(retry_after_seconds(SimpleNamespace(state=SimpleNamespace()), self.limiter))

    def test_storage_failure_degrades_to_none(self) -> None:
        broken = SimpleNamespace(limiter=SimpleNamespace(get_window_stats=lambda *a: 1 / 0))
        self.assertIsNone(retry_after_seconds(self._request((self.item, self.args)), broken))


class RateLimitedHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_429_keeps_the_detail_and_adds_retry_after(self) -> None:
        from app.interface.api.rate_limiter import limiter

        item = parse("1/hour")
        args = [f"ip:retry-after-test-{time.time_ns()}", "create_run"]
        limiter.limiter.hit(item, *args)
        request = SimpleNamespace(state=SimpleNamespace(view_rate_limit=(item, args)))

        response = await _rate_limited(request, Exception("tripped"))

        self.assertEqual(response.status_code, 429)
        self.assertIn(b"going a bit fast", response.body)
        self.assertTrue(1 <= int(response.headers["retry-after"]) <= 3601)


class CorsExposesRetryAfterTests(unittest.TestCase):
    def test_cross_origin_responses_expose_retry_after(self) -> None:
        response = TestClient(app).get("/api/health", headers={"Origin": "https://localhost"})
        exposed = response.headers.get("access-control-expose-headers", "")
        self.assertIn("retry-after", exposed.lower())


if __name__ == "__main__":
    unittest.main()
