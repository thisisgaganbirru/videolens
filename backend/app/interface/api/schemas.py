from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from ...domain.entities import RunStatus, SourceMetadata, VideoAnalysis


class RunCreateResponse(BaseModel):
    run_id: str
    status: RunStatus


class RunStatusResponse(BaseModel):
    run_id: str
    status: RunStatus
    stage: Optional[str] = None
    result: Optional[VideoAnalysis] = None
    source_metadata: Optional[SourceMetadata] = None
    error: Optional[str] = None


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    title: Optional[str] = None
    created_at: datetime


class RunListResponse(BaseModel):
    runs: list[RunSummary]
