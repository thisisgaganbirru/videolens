"""Failed credentials are limited per client IP before any key lookup or
token check (AUTH_FAILURE_LIMIT_PER_IP); successful requests never count."""

import unittest

from app.application.identify_caller import IdentifyCallerUseCase
from app.domain.errors import AuthenticationError, RateLimitedError
from app.domain.policies import is_well_formed_api_key
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository, generate_secret
from app.infrastructure.quota import credential_failures
from app.infrastructure.quota.credential_failures import CredentialFailureCounter

from .fakes import FakeTokenVerifier

BOGUS_KEY = "vl_live_" + "A" * 43


class CountingApiKeys:
    """Records every lookup, so a test can pin that a refused request never
    reached the key store."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.lookups: list[str] = []

    async def authenticate(self, secret: str):
        self.lookups.append(secret)
        return await self.inner.authenticate(secret)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FailedCredentialLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.accounts = InMemoryAccountDirectory()
        self.api_keys = CountingApiKeys(InMemoryApiKeyRepository())
        self.verifier = FakeTokenVerifier({"sub": "user-123", "email": "a@b.test", "role": "authenticated"})
        self.clock = FakeClock()
        self.counter = CredentialFailureCounter(Settings(auth_failure_limit_per_ip=3), clock=self.clock)
        self.use_case = IdentifyCallerUseCase(
            accounts=self.accounts,
            api_keys=self.api_keys,
            verifier=self.verifier,
            allow_anonymous=True,
            failures=self.counter,
        )

    async def _fail(self, ip: str, n: int) -> None:
        for _ in range(n):
            with self.assertRaises(AuthenticationError):
                await self.use_case.resolve(api_key=BOGUS_KEY, client_ip=ip)

    async def test_n_failures_then_429_without_a_lookup(self) -> None:
        await self._fail("203.0.113.1", 3)
        self.assertEqual(len(self.api_keys.lookups), 3)
        with self.assertRaises(RateLimitedError) as caught:
            await self.use_case.resolve(api_key=BOGUS_KEY, client_ip="203.0.113.1")
        self.assertEqual(len(self.api_keys.lookups), 3)
        self.assertTrue(1 <= caught.exception.retry_after_seconds <= credential_failures.WINDOW_SECONDS)

    async def test_blocked_ip_skips_token_verification_too(self) -> None:
        await self._fail("203.0.113.1", 3)
        with self.assertRaises(RateLimitedError):
            await self.use_case.resolve(authorization="Bearer eyJhbGciOi.x.y", client_ip="203.0.113.1")
        self.assertEqual(self.verifier.tokens, [])

    async def test_bad_tokens_count(self) -> None:
        self.verifier.error = ValueError("bad signature")
        for _ in range(3):
            with self.assertRaises(AuthenticationError):
                await self.use_case.resolve(authorization="Bearer eyJhbGciOi.x.y", client_ip="203.0.113.9")
        with self.assertRaises(RateLimitedError):
            await self.use_case.resolve(authorization="Bearer eyJhbGciOi.x.y", client_ip="203.0.113.9")
        self.assertEqual(len(self.verifier.tokens), 3)

    async def test_success_is_not_counted(self) -> None:
        account = await self.accounts.resolve_account("user-123", "a@b.test")
        created = await self.api_keys.issue(account.default_workspace_id, "ci", ["runs:read"], max_active=10)
        for _ in range(10):
            await self.use_case.resolve(api_key=created.secret, client_ip="203.0.113.1")
            await self.use_case.resolve(authorization="Bearer eyJhbGciOi.x.y", client_ip="203.0.113.1")
        self.assertIsNone(await self.counter.retry_after("203.0.113.1"))

    async def test_separate_ips_have_separate_budgets(self) -> None:
        await self._fail("203.0.113.1", 3)
        await self._fail("203.0.113.2", 2)
        with self.assertRaises(RateLimitedError):
            await self.use_case.resolve(api_key=BOGUS_KEY, client_ip="203.0.113.1")
        await self._fail("203.0.113.2", 1)

    async def test_the_window_ends(self) -> None:
        await self._fail("203.0.113.1", 3)
        self.clock.now += credential_failures.WINDOW_SECONDS
        await self._fail("203.0.113.1", 1)

    async def test_anonymous_requests_are_never_refused(self) -> None:
        await self._fail("203.0.113.1", 3)
        principal = await self.use_case.resolve(client_id="client-0123456789abcdef", client_ip="203.0.113.1")
        self.assertFalse(principal.authenticated)

    async def test_malformed_key_is_rejected_without_a_lookup(self) -> None:
        for key in ("vl_live_short", "vl_live_" + "A" * 44, "vl_live_" + "!" * 43):
            with self.assertRaises(AuthenticationError):
                await self.use_case.resolve(api_key=key, client_ip="198.51.100.7")
        self.assertEqual(self.api_keys.lookups, [])

    async def test_a_counter_outage_fails_open(self) -> None:
        class Broken:
            async def retry_after(self, client_ip):
                raise ConnectionError("redis down")

            async def record_failure(self, client_ip):
                raise ConnectionError("redis down")

        use_case = IdentifyCallerUseCase(
            accounts=self.accounts, api_keys=self.api_keys, verifier=self.verifier, allow_anonymous=True, failures=Broken()
        )
        with self.assertRaises(AuthenticationError):
            await use_case.resolve(api_key=BOGUS_KEY, client_ip="203.0.113.1")


class KeyFormatTests(unittest.TestCase):
    def test_every_issued_key_is_well_formed(self) -> None:
        for _ in range(50):
            secret, _prefix = generate_secret()
            self.assertTrue(is_well_formed_api_key(secret), secret)


class CounterAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_off_when_the_limit_is_zero(self) -> None:
        counter = CredentialFailureCounter(Settings(auth_failure_limit_per_ip=0))
        for _ in range(5):
            await counter.record_failure("203.0.113.1")
        self.assertIsNone(await counter.retry_after("203.0.113.1"))

    async def test_no_ip_means_no_bucket(self) -> None:
        counter = CredentialFailureCounter(Settings(auth_failure_limit_per_ip=1))
        await counter.record_failure("")
        self.assertIsNone(await counter.retry_after(""))

    async def test_distributed_mode_counts_in_redis(self) -> None:
        clock = FakeClock()
        counter = CredentialFailureCounter(
            Settings(auth_failure_limit_per_ip=2, redis_url="redis://localhost:6379/0"), clock=clock
        )

        class FakeRedis:
            def __init__(self) -> None:
                self.store: dict = {}
                self.ttls: dict = {}

            async def eval(self, script, numkeys, key, ttl):
                self.store[key] = self.store.get(key, 0) + 1
                self.ttls[key] = int(ttl)
                return self.store[key]

            async def get(self, key):
                value = self.store.get(key)
                return str(value) if value is not None else None

        redis = FakeRedis()
        counter._redis = redis
        await counter.record_failure("203.0.113.1")
        self.assertIsNone(await counter.retry_after("203.0.113.1"))
        await counter.record_failure("203.0.113.1")
        self.assertIsNotNone(await counter.retry_after("203.0.113.1"))
        (key,) = redis.store
        # Hashed, never the raw address, and it expires with its window.
        self.assertNotIn("203.0.113.1", key)
        self.assertEqual(redis.ttls[key], credential_failures.WINDOW_SECONDS)


if __name__ == "__main__":
    unittest.main()


class RouteShapeTests(unittest.TestCase):
    """End to end through the app: the 429 is the project's error shape
    with Retry-After, keyed on the same client IP as the rate limiter."""

    def test_bogus_keys_turn_into_429(self) -> None:
        from unittest.mock import patch

        from starlette.testclient import TestClient

        from app.container import container
        from app.interface.api.app import app

        counter = CredentialFailureCounter(Settings(auth_failure_limit_per_ip=2))
        client = TestClient(app)
        with patch.object(container.identify_caller_use_case, "_failures", counter):
            first = [client.get("/api/me", headers={"X-Api-Key": BOGUS_KEY}).status_code for _ in range(2)]
            blocked = client.get("/api/me", headers={"X-Api-Key": BOGUS_KEY})
        self.assertEqual(first, [401, 401])
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(set(blocked.json()), {"detail"})
        self.assertIn("Retry-After", blocked.headers)
