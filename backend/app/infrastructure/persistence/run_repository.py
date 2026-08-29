import asyncio
from datetime import datetime, timezone
from typing import Optional

from redis.asyncio import Redis

from ...domain.entities import AnalysisCompleteness, Run, RunStatus, SourceMetadata, VideoAnalysis
from ..config import Settings

# Cap on how many run_ids the per-owner history index retains, independent of
# how many a caller asks to list - bounds Redis memory regardless of how long
# RUN_TTL_SECONDS is set to.
_HISTORY_INDEX_CAP = 50


class RunStore:
    """RunRepository adapter: Redis-backed when a queue is configured
    (distributed mode), in-process dict otherwise (local dev)."""

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

    async def create(self, run_id: str, owner_id: str) -> Run:
        now = datetime.now(timezone.utc)
        run = Run(
            run_id=run_id,
            owner_id=owner_id,
            status=RunStatus.QUEUED,
            created_at=now,
            updated_at=now,
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

    async def _update(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        stage: str | None = None,
        result: VideoAnalysis | None = None,
        completeness: AnalysisCompleteness | None = None,
        source_metadata: SourceMetadata | None = None,
        error: str | None = None,
    ) -> None:
        run = await self.get(run_id)
        if run is None:
            return
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
        if error is not None:
            run.error = error
        run.updated_at = datetime.now(timezone.utc)
        await self._write(run)

    async def set_status(self, run_id: str, status: RunStatus) -> None:
        await self._update(run_id, status=status)

    async def set_stage(self, run_id: str, stage: str) -> None:
        await self._update(run_id, stage=stage)

    async def set_result(
        self,
        run_id: str,
        result: VideoAnalysis,
        completeness: AnalysisCompleteness = AnalysisCompleteness.FULL,
    ) -> None:
        await self._update(
            run_id, status=RunStatus.COMPLETE, result=result, completeness=completeness
        )

    async def set_source_metadata(self, run_id: str, metadata: SourceMetadata) -> None:
        await self._update(run_id, source_metadata=metadata)

    async def set_error(self, run_id: str, error: str) -> None:
        await self._update(run_id, status=RunStatus.FAILED, error=error)

    async def ping(self) -> bool:
        if not self._settings.queue_enabled:
            return True
        return bool(await self._client().ping())

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
