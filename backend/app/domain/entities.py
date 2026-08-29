from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class TranscriptSegment(BaseModel):
    start_seconds: float
    end_seconds: float
    text: str
    speaker: Optional[str] = None


class ScreenTextSegment(BaseModel):
    start_seconds: float
    end_seconds: float
    text: str


class AnalysisCompleteness(str, Enum):
    """What the analysis was actually able to look at.

    Deliberately *not* a field on `VideoAnalysis`: that model is handed to
    Gemini as its `response_schema`, so anything added to it becomes something
    the model fills in. This is a fact the server knows and the model must not
    be asked to assert.
    """

    FULL = "full"
    CAPTIONS_ONLY = "captions_only"


class VideoAnalysis(BaseModel):
    title: str
    summary: str
    transcript: str
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    screen_text: str
    screen_text_segments: list[ScreenTextSegment] = Field(default_factory=list)
    markdown: str


class SourceMetadata(BaseModel):
    platform: str
    source_url: str
    title: Optional[str] = None
    uploader: Optional[str] = None
    uploader_url: Optional[str] = None
    description: Optional[str] = None
    upload_date: Optional[str] = None
    like_count: Optional[int] = None
    view_count: Optional[int] = None
    comment_count: Optional[int] = None


class Run(BaseModel):
    run_id: str
    owner_id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    stage: Optional[str] = None
    result: Optional[VideoAnalysis] = None
    error: Optional[str] = None
    source_metadata: Optional[SourceMetadata] = None
    completeness: AnalysisCompleteness = AnalysisCompleteness.FULL


class CapabilityState(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class Capability(BaseModel):
    """One thing the service needs in order to accept work, and whether it is
    actually there right now.

    `probed` is the honest half of this record: True means the check really
    exercised the dependency, False means it only read configuration. A health
    report that cannot tell those apart eventually reports "ok" for something
    that has never once worked.
    """

    name: str
    state: CapabilityState
    detail: str
    probed: bool
    # Operator-only half, excluded from serialization: this report is served
    # unauthenticated, so component versions, deployment topology and live
    # quota counts must not travel with it. Same split as
    # `UserFacingError.log_detail`, for the same reason.
    log_detail: Optional[str] = Field(default=None, exclude=True)


class CapabilityReport(BaseModel):
    state: CapabilityState
    mode: str
    capabilities: list[Capability]


@dataclass(frozen=True)
class Principal:
    subject: str
    authenticated: bool


@dataclass
class SavedUpload:
    path: str
    run_dir: str
    metadata: Optional[SourceMetadata] = None


@dataclass
class CaptionTrack:
    """A subtitle track recovered when the media itself could not be fetched.

    Carries no timing: the pipeline only reaches for this once the video is
    already unavailable, so the goal is a usable transcript, not a second-rate
    imitation of the full analysis.
    """

    text: str
    language: str
    automatic: bool
    metadata: Optional[SourceMetadata] = None
