import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from redis.asyncio import Redis

from ...domain.entities import (
    AnalysisCompleteness,
    MediaVisuals,
    Run,
    RunStatus,
    SourceMetadata,
    VideoAnalysis,
)
from ..config import Settings

# Cap on how many run_ids the per-owner history index retains, independent of
# how many a caller asks to list - bounds Redis memory regardless of how long
# RUN_TTL_SECONDS is set to.
_HISTORY_INDEX_CAP = 50

# A run in either state has ended; `_update` never writes to it again.
_SETTLED = (RunStatus.COMPLETE, RunStatus.FAILED)

# Write the run back only if it still exists and has not ended in the
# meantime. The status check runs inside Redis, so a worker's result and the
# stale-run sweep's failure cannot both land: the second one sees the first.
_WRITE_UNLESS_SETTLED = """
local current = redis.call('GET', KEYS[1])
if not current then
  return 0
end
local ok, doc = pcall(cjson.decode, current)
if ok and type(doc) == 'table' and (doc.status == 'complete' or doc.status == 'failed') then
  return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
return 1
"""


class RunStore:
    """RunRepository adapter: Redis-backed when a queue is configured
    (distributed mode), in-process dict otherwise (local dev).

    Retention is `RUN_TTL_SECONDS` (1 hour by default): the browser keeps
    History in IndexedDB now, so the server only holds a run long enough to
    deliver it. Every write re-arms the TTL, so a run that finishes late still
    gets the full window after it reaches complete/failed; those two writes
    also re-arm the owner's history index so `GET /api/runs` keeps listing it.
    The in-memory store applies the same window by pruning on write.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._memory: dict[str, Run] = {}
        self._lock = asyncio.Lock()
        self._redis: Redis | None = None

    def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self._settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _key(run_id: str) -> str:
        return f"videolens:run:{run_id}"

    @staticmethod
    def _owner_index_key(owner_id: str) -> str:
        return f"videolens:owner:{owner_id}:runs"

    async def _write(self, run: Run) -> None:
        if self._settings.queue_enabled:
            await self._client().set(
                self._key(run.run_id),
                run.model_dump_json(),
                ex=self._settings.run_ttl_seconds,
            )
            return
        async with self._lock:
            self._memory[run.run_id] = run
            self._prune_memory()

    def _prune_memory(self) -> None:
        # Same retention as Redis's `ex=`: measured from the last write.
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self._settings.run_ttl_seconds)
        expired = [run_id for run_id, run in self._memory.items() if run.updated_at < cutoff]
        for run_id in expired:
            del self._memory[run_id]

    async def _refresh_owner_index(self, owner_id: str) -> None:
        if self._settings.queue_enabled:
            await self._client().expire(
                self._owner_index_key(owner_id), self._settings.run_ttl_seconds
            )

    async def create(
        self,
        run_id: str,
        owner_id: str,
        *,
        source_kind: str | None = None,
        platform: str | None = None,
        duration_seconds: float | None = None,
        media_tier: str | None = None,
        admitted_byok: bool = False,
    ) -> Run:
        now = datetime.now(timezone.utc)
        run = Run(
            run_id=run_id,
            owner_id=owner_id,
            status=RunStatus.QUEUED,
            created_at=now,
            updated_at=now,
            source_kind=source_kind,
            platform=platform,
            duration_seconds=duration_seconds,
            media_tier=media_tier,
            admitted_byok=admitted_byok,
        )
        await self._write(run)
        if self._settings.queue_enabled:
            index_key = self._owner_index_key(owner_id)
            client = self._client()
            await client.zadd(index_key, {run_id: now.timestamp()})
            await client.zremrangebyrank(index_key, 0, -(_HISTORY_INDEX_CAP + 1))
            await client.expire(index_key, self._settings.run_ttl_seconds)
        return run

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]:
        if self._settings.queue_enabled:
            run_ids = await self._client().zrevrange(self._owner_index_key(owner_id), 0, limit - 1)
            runs = [await self.get(run_id) for run_id in run_ids]
            return [run for run in runs if run is not None]
        async with self._lock:
            # Dicts preserve insertion order. Start newest-first so Python's
            # stable sort retains that order when the platform clock gives
            # multiple runs the same timestamp.
            matches = [
                run
                for run in reversed(self._memory.values())
                if run.owner_id == owner_id
            ]
        matches.sort(key=lambda run: run.created_at, reverse=True)
        return matches[:limit]

    async def get(self, run_id: str) -> Optional[Run]:
        if self._settings.queue_enabled:
            payload = await self._client().get(self._key(run_id))
            return Run.model_validate_json(payload) if payload else None
        async with self._lock:
            return self._memory.get(run_id)

    @staticmethod
    def _apply(
        run: Run,
        *,
        status: RunStatus | None = None,
        stage: str | None = None,
        result: VideoAnalysis | None = None,
        completeness: AnalysisCompleteness | None = None,
        source_metadata: SourceMetadata | None = None,
        duration_seconds: float | None = None,
        visuals: MediaVisuals | None = None,
        error: str | None = None,
    ) -> None:
        if status is not None:
            run.status = status
        if stage is not None:
            run.stage = stage
        if result is not None:
            run.result = result
        if completeness is not None:
            run.completeness = completeness
        if source_metadata is not None:
            run.source_metadata = source_metadata
        if duration_seconds is not None:
            run.duration_seconds = duration_seconds
        if visuals is not None:
            if visuals.thumbnail is not None:
                run.thumbnail = visuals.thumbnail
            if visuals.width is not None and visuals.height is not None:
                run.width = visuals.width
                run.height = visuals.height
        if error is not None:
            run.error = error
        run.updated_at = datetime.now(timezone.utc)

    async def _update(self, run_id: str, **changes) -> Run | None:
        """Apply `changes` and write the run back. Returns the written run,
        or None when nothing was written: the run is gone (TTL, account
        deletion), or it has already ended. A complete or failed run is
        final - whichever of the worker's result and the stale-run sweep's
        failure lands first is the outcome every later read sees, so a late
        worker can neither resurrect a run the client was told failed nor a
        late sweep fail one that completed. The check and the write are one
        step (a Lua script in Redis, the lock in memory)."""
        if not self._settings.queue_enabled:
            async with self._lock:
                run = self._memory.get(run_id)
                if run is None or run.status in _SETTLED:
                    return None
                self._apply(run, **changes)
                self._prune_memory()
                return run
        run = await self.get(run_id)
        if run is None or run.status in _SETTLED:
            return None
        self._apply(run, **changes)
        written = await self._client().eval(
            _WRITE_UNLESS_SETTLED,
            1,
            self._key(run_id),
            run.model_dump_json(),
            self._settings.run_ttl_seconds,
        )
        return run if int(written or 0) == 1 else None

    async def set_status(self, run_id: str, status: RunStatus) -> None:
        await self._update(run_id, status=status)

    async def set_stage(self, run_id: str, stage: str) -> None:
        await self._update(run_id, stage=stage)

    async def set_result(
        self,
        run_id: str,
        result: VideoAnalysis,
        completeness: AnalysisCompleteness = AnalysisCompleteness.FULL,
    ) -> bool:
        run = await self._update(
            run_id, status=RunStatus.COMPLETE, result=result, completeness=completeness
        )
        if run is None:
            return False
        await self._refresh_owner_index(run.owner_id)
        return True

    async def set_source_metadata(self, run_id: str, metadata: SourceMetadata) -> None:
        await self._update(run_id, source_metadata=metadata)

    async def set_duration(self, run_id: str, duration_seconds: float) -> None:
        await self._update(run_id, duration_seconds=duration_seconds)

    async def set_visuals(self, run_id: str, visuals: MediaVisuals) -> None:
        await self._update(run_id, visuals=visuals)

    async def set_error(self, run_id: str, error: str) -> bool:
        run = await self._update(run_id, status=RunStatus.FAILED, error=error)
        if run is None:
            return False
        await self._refresh_owner_index(run.owner_id)
        return True

    async def delete_for_owner(self, owner_id: str) -> int:
        """Account deletion. In Redis the owner index is the only way to find
        an owner's runs; it holds at most `_HISTORY_INDEX_CAP` ids, and any
        older run would already be near its TTL. A run a worker is still
        processing stays deleted: `_update` reads before it writes and skips a
        run that is gone."""
        if self._settings.queue_enabled:
            client = self._client()
            index_key = self._owner_index_key(owner_id)
            run_ids = await client.zrange(index_key, 0, -1)
            keys = [self._key(run_id) for run_id in run_ids]
            removed = await client.delete(*keys) if keys else 0
            await client.delete(index_key)
            return int(removed or 0)
        async with self._lock:
            doomed = [run_id for run_id, run in self._memory.items() if run.owner_id == owner_id]
            for run_id in doomed:
                del self._memory[run_id]
        return len(doomed)

    async def ping(self) -> bool:
        if not self._settings.queue_enabled:
            return True
        return bool(await self._client().ping())

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
