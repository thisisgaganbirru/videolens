from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from ...domain.entities import AnalysisCompleteness, RunStatus, SourceMetadata, VideoAnalysis


class RunCreateResponse(BaseModel):
    run_id: str
    status: RunStatus


class RunStatusResponse(BaseModel):
    run_id: str
    status: RunStatus
    stage: Optional[str] = None
    result: Optional[VideoAnalysis] = None
    source_metadata: Optional[SourceMetadata] = None
    completeness: AnalysisCompleteness = AnalysisCompleteness.FULL
    error: Optional[str] = None
    source_kind: Optional[Literal["link", "file"]] = None
    platform: Optional[str] = None
    duration_seconds: Optional[float] = None
    # Everything the browser needs to file this run into its own History
    # (IndexedDB) once delivered: a <=20 KB `data:image/jpeg;base64,...`
    # poster and the display size (rotation applied). None for audio and for
    # runs stored before these existed.
    thumbnail: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    orientation: Optional[Literal["landscape", "portrait"]] = None


class RunSummary(BaseModel):
    """One history card. Every field past `created_at` is optional: runs
    stored before they existed have none of them, and the derivations live in
    `domain/run_facts.py`, not here."""

    run_id: str
    status: RunStatus
    title: Optional[str] = None
    created_at: datetime
    source_kind: Optional[Literal["link", "file"]] = None
    # "youtube" | "instagram" | "tiktok" | "audio_file" | "video_file" | "other"
    platform: Optional[str] = None
    duration_seconds: Optional[float] = None
    summary_snippet: Optional[str] = None
    orientation: Optional[Literal["landscape", "portrait"]] = None
    # Cheap and useful for the card's shape. The thumbnail is deliberately
    # not here: a 20-row list of inline JPEGs is ~0.5 MB per poll.
    width: Optional[int] = None
    height: Optional[int] = None


class RunListResponse(BaseModel):
    runs: list[RunSummary]
