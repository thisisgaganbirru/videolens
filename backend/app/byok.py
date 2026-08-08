from redis.asyncio import Redis

from .config import settings

# Long enough to comfortably outlive WORKER_JOB_TIMEOUT_SECONDS (default 600s)
# as a safety net if the worker never calls take(); short enough that a key
# left behind by a crashed worker doesn't linger.
_KEY_TTL_SECONDS = 900


class ByokKeyStore:
    """Transient, single-use storage for a client-supplied Gemini API key.

    A bring-your-own-key run has to cross the process boundary between the
    API process (which receives the key) and the worker process (which
    actually calls Gemini with it) - kept separate from arq's own job
    arguments so the raw key never appears in arq's job-start/result
    logging, and deleted immediately after the worker reads it rather than
    waiting out a TTL. Never written to RunStore.
    """

    def __init__(self) -> None:
        self._redis: Redis | None = None
        self._memory: dict[str, str] = {}

    def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _key(run_id: str) -> str:
        return f"videolens:byok:{run_id}"

    async def store(self, run_id: str, api_key: str) -> None:
        if settings.queue_enabled:
            await self._client().set(self._key(run_id), api_key, ex=_KEY_TTL_SECONDS)
            return
        self._memory[run_id] = api_key

    async def take(self, run_id: str) -> str | None:
        """Read-and-delete: the stored key is used at most once."""
        if settings.queue_enabled:
            client = self._client()
            value = await client.get(self._key(run_id))
            if value is not None:
                await client.delete(self._key(run_id))
            return value
        return self._memory.pop(run_id, None)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None


byok_keys = ByokKeyStore()
