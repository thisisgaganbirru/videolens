from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class VideoAnalysis(BaseModel):
    title: str
    summary: str
    transcript: str
    screen_text: str
    markdown: str


class Job(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    stage: Optional[str] = None
    result: Optional[VideoAnalysis] = None
    error: Optional[str] = None


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    stage: Optional[str] = None
    result: Optional[VideoAnalysis] = None
    error: Optional[str] = None
