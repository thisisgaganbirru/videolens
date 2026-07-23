import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from .config import settings
from .models import Job, JobStatus, VideoAnalysis

logger = logging.getLogger("videolens")

TERMINAL_STATUSES = (JobStatus.COMPLETE, JobStatus.FAILED)


class JobStore:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create(self, job_id: str) -> Job:
        now = datetime.now(timezone.utc)
        job = Job(job_id=job_id, status=JobStatus.QUEUED, created_at=now, updated_at=now)
        async with self._lock:
            self._jobs[job_id] = job
        return job

    async def get(self, job_id: str) -> Optional[Job]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def set_status(self, job_id: str, status: JobStatus) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = status
                job.updated_at = datetime.now(timezone.utc)

    async def set_stage(self, job_id: str, stage: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.stage = stage
                job.updated_at = datetime.now(timezone.utc)

    async def set_result(self, job_id: str, result: VideoAnalysis) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = JobStatus.COMPLETE
                job.result = result
                job.updated_at = datetime.now(timezone.utc)

    async def set_error(self, job_id: str, error: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = JobStatus.FAILED
                job.error = error
                job.updated_at = datetime.now(timezone.utc)

    async def sweep_expired(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.job_ttl_seconds)
        async with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.status in TERMINAL_STATUSES and job.updated_at < cutoff
            ]
            for job_id in expired:
                del self._jobs[job_id]
        return len(expired)

    async def sweep_loop(self, interval_seconds: int = 300) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                removed = await self.sweep_expired()
                if removed:
                    logger.info("Swept %d expired job(s)", removed)
            except Exception:
                logger.exception("Job sweep failed")


job_store = JobStore()
