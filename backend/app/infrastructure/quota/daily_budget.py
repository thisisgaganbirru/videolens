from datetime import datetime, timezone

from redis.asyncio import Redis

from ...domain.entities import SpendClaim
from ..config import Settings

# Two days: covers a run started just before UTC midnight without leaking keys forever.
_KEY_TTL_SECONDS = 172800

# Take one unit only while under the cap, in one atomic step: a refused
# request leaves the counter alone, so a refund later always lands below
# the cap instead of on top of refused attempts. Missing keys GET as false.
_CONSUME = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
if used >= tonumber(ARGV[1]) then return 0 end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""

# Give one back, never below zero (a key that expired stays absent).
_REFUND = """
if tonumber(redis.call('GET', KEYS[1]) or '0') > 0 then redis.call('DECR', KEYS[1]) end
return 1
"""


def _today() -> str:
    return f"{datetime.now(timezone.utc):%Y-%m-%d}"


class DailyBudget:
    """SpendCap adapter: caps total accepted runs per UTC day, independent
    of per-IP limits.

    Per-IP rate limiting stops one abuser; it does nothing once requests are
    spread across many IPs (organic traffic or distributed abuse). This is
    the backstop that bounds total Gemini spend regardless of where runs
    come from. A unit taken by a run that never reaches Gemini goes back
    (`release`), so rejected uploads and dead links cannot exhaust it.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis: Redis | None = None
        self._memory: dict[str, int] = {}
        # run_id -> the day its unit was taken from (local mode).
        self._held: dict[str, str] = {}

    def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self._settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _day_key(day: str) -> str:
        return f"videolens:runs:{day}"

    @classmethod
    def _key(cls) -> str:
        return cls._day_key(_today())

    @staticmethod
    def _held_key(run_id: str) -> str:
        return f"videolens:runs:held:{run_id}"

    async def try_consume(self) -> SpendClaim | None:
        """A claim if a run may proceed, None if today's cap is hit."""
        day = _today()
        if self._settings.daily_run_cap <= 0:
            return SpendClaim(day=day, counted=False)
        key = self._day_key(day)
        if self._settings.queue_enabled:
            allowed = await self._client().eval(
                _CONSUME, 1, key, self._settings.daily_run_cap, _KEY_TTL_SECONDS
            )
            return SpendClaim(day=day) if int(allowed) else None
        # Yesterday's counters are dead weight in a long-lived local process.
        self._memory = {k: v for k, v in self._memory.items() if k == key}
        count = self._memory.get(key, 0)
        if count >= self._settings.daily_run_cap:
            return None
        self._memory[key] = count + 1
        return SpendClaim(day=day)

    async def refund(self, claim: SpendClaim) -> None:
        if not claim.counted or not claim.day:
            return
        # The claim's own day, not today's: a refund after midnight never
        # frees a unit on the new day.
        key = self._day_key(claim.day)
        if self._settings.queue_enabled:
            await self._client().eval(_REFUND, 1, key)
            return
        if self._memory.get(key, 0) > 0:
            self._memory[key] -= 1

    async def hold(self, run_id: str, claim: SpendClaim) -> None:
        if not claim.counted or not claim.day:
            return
        if self._settings.queue_enabled:
            await self._client().set(self._held_key(run_id), claim.day, ex=_KEY_TTL_SECONDS)
            return
        self._held[run_id] = claim.day

    async def release(self, run_id: str, *, refund: bool) -> bool:
        if self._settings.queue_enabled:
            # GET + DEL in one MULTI: of two racing releases only one sees
            # the day, so a unit is handed back at most once.
            async with self._client().pipeline(transaction=True) as pipe:
                pipe.get(self._held_key(run_id))
                pipe.delete(self._held_key(run_id))
                day, _ = await pipe.execute()
        else:
            day = self._held.pop(run_id, None)
        if not day or not refund:
            return False
        await self.refund(SpendClaim(day=day))
        return True

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
