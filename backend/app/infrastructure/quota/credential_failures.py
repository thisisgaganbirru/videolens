import hashlib
import time

from redis.asyncio import Redis

from ..config import Settings

# Fixed windows: simple, one key per IP per window, and the 429's
# Retry-After is just the time left in the current one.
WINDOW_SECONDS = 900

# Count one failure and arm the key's expiry in one step, so a key can never
# be left without a TTL.
_RECORD = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


class CredentialFailureCounter:
    """CredentialFailureGuard adapter: failed credentials per client IP per
    15-minute window. Redis-backed in distributed mode (shared across
    replicas), an in-process dict otherwise - the same duality as
    DailyBudget. IPs are hashed before they become key names."""

    def __init__(self, settings: Settings, *, clock=time.time) -> None:
        self._settings = settings
        self._clock = clock
        self._redis: Redis | None = None
        self._memory: dict[str, int] = {}
        self._memory_window = -1

    def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self._settings.redis_url, decode_responses=True)
        return self._redis

    @property
    def _limit(self) -> int:
        return self._settings.auth_failure_limit_per_ip

    def _window(self) -> int:
        return int(self._clock() // WINDOW_SECONDS)

    @staticmethod
    def _key(window: int, client_ip: str) -> str:
        digest = hashlib.sha256(client_ip.encode()).hexdigest()[:32]
        return f"videolens:authfail:{window}:{digest}"

    def _local(self, window: int) -> dict[str, int]:
        if window != self._memory_window:
            self._memory = {}
            self._memory_window = window
        return self._memory

    async def retry_after(self, client_ip: str) -> int | None:
        # No IP (a direct socket with no peer) means no bucket rather than
        # one shared one that would lock everyone out at once.
        if self._limit <= 0 or not client_ip:
            return None
        window = self._window()
        key = self._key(window, client_ip)
        if self._settings.queue_enabled:
            raw = await self._client().get(key)
            count = int(raw) if raw else 0
        else:
            count = self._local(window).get(key, 0)
        if count < self._limit:
            return None
        return max(1, int((window + 1) * WINDOW_SECONDS - self._clock()))

    async def record_failure(self, client_ip: str) -> None:
        if self._limit <= 0 or not client_ip:
            return
        window = self._window()
        key = self._key(window, client_ip)
        if self._settings.queue_enabled:
            await self._client().eval(_RECORD, 1, key, WINDOW_SECONDS)
            return
        counts = self._local(window)
        counts[key] = counts.get(key, 0) + 1

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
