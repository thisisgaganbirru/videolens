from datetime import datetime, timezone

from redis.asyncio import Redis

from ..config import Settings

# Two days: covers a run started just before UTC midnight without leaking keys forever.
_KEY_TTL_SECONDS = 172800


class DailyBudget:
    """SpendCap adapter: caps total accepted runs per UTC day, independent
    of per-IP limits.

    Per-IP rate limiting stops one abuser; it does nothing once requests are
    spread across many IPs (organic traffic or distributed abuse). This is
    the backstop that bounds total Gemini spend regardless of where runs
    come from.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis: Redis | None = None
        self._memory: dict[str, int] = {}

    def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self._settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _key() -> str:
        return f"videolens:runs:{datetime.now(timezone.utc):%Y-%m-%d}"

    async def try_consume(self) -> bool:
        """Returns True if a run may proceed, False if today's cap is hit."""
        if self._settings.daily_run_cap <= 0:
            return True
        key = self._key()
        if self._settings.queue_enabled:
            count = await self._client().incr(key)
            if count == 1:
                await self._client().expire(key, _KEY_TTL_SECONDS)
            return count <= self._settings.daily_run_cap
        count = self._memory.get(key, 0) + 1
        self._memory[key] = count
        return count <= self._settings.daily_run_cap

    async def remaining(self) -> int | None:
        """Runs still available under today's cap, or None when uncapped.

        Read-only on purpose: health reporting must never consume the budget
        it is reporting on.
        """
        if self._settings.daily_run_cap <= 0:
            return None
        key = self._key()
        if self._settings.queue_enabled:
            raw = await self._client().get(key)
            used = int(raw) if raw else 0
        else:
            used = self._memory.get(key, 0)
        return max(0, self._settings.daily_run_cap - used)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
