import asyncio
from datetime import datetime, timezone
from typing import Optional

from redis.asyncio import Redis

from .config import settings
from .models import Run, RunStatus, VideoAnalysis


class RunStore:
    def __init__(self) -> None:
        self._memory: dict[str, Run] = {}
        self._lock = asyncio.Lock()
        self._redis: Redis | None = None

    def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _key(run_id: str) -> str:
        return f"videolens:run:{run_id}"

    async def _write(self, run: Run) -> None:
        if settings.queue_enabled:
            await self._client().set(
                self._key(run.run_id),
                run.model_dump_json(),
                ex=settings.run_ttl_seconds,
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
        return run

    async def get(self, run_id: str) -> Optional[Run]:
        if settings.queue_enabled:
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
        if error is not None:
            run.error = error
        run.updated_at = datetime.now(timezone.utc)
        await self._write(run)

    async def set_status(self, run_id: str, status: RunStatus) -> None:
        await self._update(run_id, status=status)

    async def set_stage(self, run_id: str, stage: str) -> None:
        await self._update(run_id, stage=stage)

    async def set_result(self, run_id: str, result: VideoAnalysis) -> None:
        await self._update(run_id, status=RunStatus.COMPLETE, result=result)

    async def set_error(self, run_id: str, error: str) -> None:
        await self._update(run_id, status=RunStatus.FAILED, error=error)

    async def ping(self) -> bool:
        if not settings.queue_enabled:
            return True
        return bool(await self._client().ping())

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None


run_store = RunStore()
