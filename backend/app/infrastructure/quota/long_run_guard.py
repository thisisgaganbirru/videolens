import asyncio
import hashlib
import time

from redis.asyncio import Redis

from ..config import Settings

# Take the slot when it is free or already ours (re-arming the expiry either
# way); refuse when another run holds it. One atomic step, so two concurrent
# long runs cannot both see it free.
_ACQUIRE = """
local holder = redis.call('GET', KEYS[1])
if holder and holder ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return 1
"""

# Free it only for the run that holds it: a run whose slot already expired
# and was taken by a newer one must not free the newer one's.
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


class LongRunSlots:
    """LongRunGuard adapter: one slot per account for runs above the standard
    media limits. Redis-backed in distributed mode (API and worker are
    different processes), an in-process dict otherwise.

    The slot expires after a whole long job could have taken plus the same
    margin the stale-run check uses (`WORKER_LONG_JOB_TIMEOUT_SECONDS + 120`),
    so a worker that dies mid-run frees the account at about the moment the
    run itself is reported as abandoned. Keys are hashed: the guard only
    needs to tell accounts apart.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis: Redis | None = None
        self._memory: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    @property
    def ttl_seconds(self) -> int:
        return self._settings.long_job_timeout_seconds + 120

    def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self._settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _key(key: str) -> str:
        digest = hashlib.sha256(key.encode()).hexdigest()[:32]
        return f"videolens:longrun:{digest}"

    async def try_acquire(self, key: str, run_id: str) -> bool:
        name = self._key(key)
        if self._settings.queue_enabled:
            return bool(await self._client().eval(_ACQUIRE, 1, name, run_id, self.ttl_seconds))
        async with self._lock:
            now = time.monotonic()
            held = self._memory.get(name)
            if held and held[0] != run_id and held[1] > now:
                return False
            self._memory[name] = (run_id, now + self.ttl_seconds)
            return True

    async def release(self, key: str, run_id: str) -> None:
        name = self._key(key)
        if self._settings.queue_enabled:
            await self._client().eval(_RELEASE, 1, name, run_id)
            return
        async with self._lock:
            held = self._memory.get(name)
            if held and held[0] == run_id:
                del self._memory[name]

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
