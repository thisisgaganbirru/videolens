import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional

from .models import Job, JobStatus, VideoAnalysis


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


job_store = JobStore()
