import hashlib
import json
from datetime import datetime, time, timedelta, timezone

from redis.asyncio import Redis

from ...domain.entities import FreeRunClaim, FreeRunStatus
from ..config import Settings

# Two days, like DailyBudget: outlives the UTC day a key counts without
# leaking keys forever.
_KEY_TTL_SECONDS = 172800

# Check both counters, then take from both - in one atomic step, so a
# rejected request never burns a run and two concurrent requests can't both
# take the last one. KEYS[2] (the IP key) is only passed when that backstop
# is on. Missing keys GET as false, hence `or '0'`.
_CONSUME = """
local device = tonumber(redis.call('GET', KEYS[1]) or '0')
if device >= tonumber(ARGV[1]) then return 0 end
if #KEYS > 1 then
  local ip = tonumber(redis.call('GET', KEYS[2]) or '0')
  if ip >= tonumber(ARGV[2]) then return 0 end
end
for i = 1, #KEYS do
  redis.call('INCR', KEYS[i])
  redis.call('EXPIRE', KEYS[i], ARGV[3])
end
return 1
"""

# Hand a run back, never taking a counter below zero (a key that expired in
# between simply stays absent).
_REFUND = """
for i = 1, #KEYS do
  if tonumber(redis.call('GET', KEYS[i]) or '0') > 0 then redis.call('DECR', KEYS[i]) end
end
return 1
"""


def _today() -> str:
    return f"{datetime.now(timezone.utc):%Y-%m-%d}"


def next_utc_midnight() -> datetime:
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, tzinfo=timezone.utc)


class FreeRunAllowanceStore:
    """FreeRunAllowance adapter: per-device and per-IP counters, keyed by UTC
    day. Redis-backed in distributed mode (shared across replicas), an
    in-process dict otherwise - same duality as DailyBudget.

    IPs are hashed before they become key names: the counter only needs to
    tell two IPs apart, not to remember them.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis: Redis | None = None
        self._memory: dict[str, int] = {}
        self._memory_day = ""
        # run_id -> the counter keys its free run incremented (local mode).
        self._held: dict[str, list[str]] = {}

    @property
    def enabled(self) -> bool:
        return self._settings.free_runs_per_device > 0

    def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self._settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _held_key(run_id: str) -> str:
        return f"videolens:free:held:{run_id}"

    @staticmethod
    def _device_key(day: str, device_id: str) -> str:
        return f"videolens:free:device:{day}:{device_id}"

    @staticmethod
    def _ip_key(day: str, client_ip: str) -> str:
        digest = hashlib.sha256(client_ip.encode()).hexdigest()[:32]
        return f"videolens:free:ip:{day}:{digest}"

    def _keys(self, day: str, device_id: str, client_ip: str) -> list[str]:
        keys = [self._device_key(day, device_id)]
        # No IP (a direct socket with no peer) means no backstop rather than
        # one shared "anonymous" bucket that would lock everyone out at once.
        if self._settings.free_runs_per_ip > 0 and client_ip:
            keys.append(self._ip_key(day, client_ip))
        return keys

    def _local(self, day: str) -> dict[str, int]:
        # Yesterday's counters are dead weight in a long-lived local process.
        if day != self._memory_day:
            self._memory = {}
            self._memory_day = day
        return self._memory

    async def status(self, device_id: str) -> FreeRunStatus:
        limit = self._settings.free_runs_per_device
        resets_at = next_utc_midnight()
        if limit <= 0:
            return FreeRunStatus(enabled=False, limit=0, used=0, remaining=0, resets_at=resets_at)
        key = self._device_key(_today(), device_id)
        if self._settings.queue_enabled:
            raw = await self._client().get(key)
            used = int(raw) if raw else 0
        else:
            used = self._local(_today()).get(key, 0)
        used = min(used, limit)
        return FreeRunStatus(enabled=True, limit=limit, used=used, remaining=limit - used, resets_at=resets_at)

    async def try_consume(self, device_id: str, client_ip: str) -> FreeRunClaim | None:
        day = _today()
        keys = self._keys(day, device_id, client_ip)
        limits = (self._settings.free_runs_per_device, self._settings.free_runs_per_ip)
        if self._settings.queue_enabled:
            allowed = await self._client().eval(_CONSUME, len(keys), *keys, *limits, _KEY_TTL_SECONDS)
            if not int(allowed):
                return None
        else:
            counts = self._local(day)
            if any(counts.get(key, 0) >= limit for key, limit in zip(keys, limits)):
                return None
            for key in keys:
                counts[key] = counts.get(key, 0) + 1
        return FreeRunClaim(device_id=device_id, client_ip=client_ip, day=day)

    async def refund(self, claim: FreeRunClaim) -> None:
        await self._refund_keys(self._keys(claim.day, claim.device_id, claim.client_ip))

    async def _refund_keys(self, keys: list[str]) -> None:
        if self._settings.queue_enabled:
            await self._client().eval(_REFUND, len(keys), *keys)
            return
        # Keys carry their UTC day, so a refund after midnight lands on the
        # day the run was taken from. Locally yesterday's counters are gone
        # (`_local` dropped them), and the >0 guard makes that a no-op.
        for key in keys:
            if self._memory.get(key, 0) > 0:
                self._memory[key] -= 1

    async def hold(self, run_id: str, claim: FreeRunClaim) -> None:
        # The resolved counter keys (day-scoped, IP already hashed) rather
        # than the claim itself: the raw IP is never written anywhere.
        keys = self._keys(claim.day, claim.device_id, claim.client_ip)
        if self._settings.queue_enabled:
            await self._client().set(self._held_key(run_id), json.dumps(keys), ex=_KEY_TTL_SECONDS)
            return
        self._held[run_id] = keys

    async def release(self, run_id: str, *, refund: bool) -> bool:
        if self._settings.queue_enabled:
            # GET + DEL in one MULTI: of two racing releases only one sees
            # the value, so a run is handed back at most once.
            async with self._client().pipeline(transaction=True) as pipe:
                pipe.get(self._held_key(run_id))
                pipe.delete(self._held_key(run_id))
                raw, _ = await pipe.execute()
            keys = json.loads(raw) if raw else None
        else:
            keys = self._held.pop(run_id, None)
        if not keys or not refund:
            return False
        await self._refund_keys(keys)
        return True

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
