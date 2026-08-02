import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from .config import settings
from .models import Run, RunStatus, VideoAnalysis

logger = logging.getLogger("videolens")

TERMINAL_STATUSES = (RunStatus.COMPLETE, RunStatus.FAILED)


class RunStore:
    def __init__(self) -> None:
        self._runs: Dict[str, Run] = {}
        self._lock = asyncio.Lock()

    async def create(self, run_id: str) -> Run:
        now = datetime.now(timezone.utc)
        run = Run(run_id=run_id, status=RunStatus.QUEUED, created_at=now, updated_at=now)
        async with self._lock:
            self._runs[run_id] = run
        return run

    async def get(self, run_id: str) -> Optional[Run]:
        async with self._lock:
            return self._runs.get(run_id)

    async def set_status(self, run_id: str, status: RunStatus) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.status = status
                run.updated_at = datetime.now(timezone.utc)

    async def set_stage(self, run_id: str, stage: str) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.stage = stage
                run.updated_at = datetime.now(timezone.utc)

    async def set_result(self, run_id: str, result: VideoAnalysis) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.status = RunStatus.COMPLETE
                run.result = result
                run.updated_at = datetime.now(timezone.utc)

    async def set_error(self, run_id: str, error: str) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.status = RunStatus.FAILED
                run.error = error
                run.updated_at = datetime.now(timezone.utc)

    async def sweep_expired(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.run_ttl_seconds)
        async with self._lock:
            expired = [
                run_id
                for run_id, run in self._runs.items()
                if run.status in TERMINAL_STATUSES and run.updated_at < cutoff
            ]
            for run_id in expired:
                del self._runs[run_id]
        return len(expired)

    async def sweep_loop(self, interval_seconds: int = 300) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                removed = await self.sweep_expired()
                if removed:
                    logger.info("Swept %d expired run(s)", removed)
            except Exception:
                logger.exception("Run sweep failed")


run_store = RunStore()
