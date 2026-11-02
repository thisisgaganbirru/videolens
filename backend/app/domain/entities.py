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
    # Facts about the media, not the person. All optional with a None default
    # so a run stored before they existed still deserializes. `source_kind` is
    # "link" or "file"; `platform` is only stored for file runs ("audio_file" /
    # "video_file", from the extension - the filename itself is never kept),
    # link runs derive theirs from `source_metadata` at read time
    # (see domain/run_facts.py).
    source_kind: Optional[str] = None
    platform: Optional[str] = None
    duration_seconds: Optional[float] = None
    # What the browser needs to file the run in its own History (IndexedDB)
    # once it has been delivered. Still media facts only: a <=20 KB JPEG
    # poster as a `data:image/jpeg;base64,...` URL, and the *display*
    # dimensions (rotation applied, so a phone-shot portrait clip is taller
    # than wide). None for audio, for runs stored before these existed, and
    # whenever capturing them failed - which never fails the run.
    thumbnail: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


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


class ReleaseEntry(BaseModel):
    name: str
    tag: str
    published_at: str
    url: str


class LatestRelease(BaseModel):
    """What an installed APK needs to decide whether it is out of date.

    `version_code` is the Android build number, which is the only field the
    update check compares - `version_name` and `url` exist to describe the
    update once one is found.
    """

    version_code: int
    version_name: str
    url: str


class ReleaseIndex(BaseModel):
    releases: list[ReleaseEntry]
    latest: Optional[LatestRelease] = None


@dataclass(frozen=True)
class Principal:
    subject: str
    authenticated: bool


@dataclass
class SavedUpload:
    path: str
    run_dir: str
    metadata: Optional[SourceMetadata] = None
    # yt-dlp's hints for the history poster: candidate poster image URLs
    # (best first) and the reported video size. Unset for uploads and for the
    # direct-HTTP route, which have no publisher info to offer.
    thumbnail_urls: tuple[str, ...] = ()
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass(frozen=True)
class MediaVisuals:
    """The poster and display size `MediaProcessor.describe_visuals` found.
    Every field may be None - a missing poster is a cosmetic gap, not an
    error."""

    thumbnail: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


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
    # yt-dlp's own reported length, when it gave one. The media was never
    # downloaded on this path, so there is nothing to ffprobe.
    duration_seconds: Optional[float] = None
    # Same poster hints as `SavedUpload` - the info dict is fetched either way.
    thumbnail_urls: tuple[str, ...] = ()
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass(frozen=True)
class FreeRunStatus:
    """Where one device stands against today's free-run allowance.

    `used` is the device's own count; the per-IP backstop is deliberately
    not reflected here (it is not something a device can see or act on).
    `enabled=False` means there is no free-run limit at all.
    """

    enabled: bool
    limit: int
    used: int
    remaining: int
    resets_at: datetime


@dataclass(frozen=True)
class FreeRunClaim:
    """One free run taken from the allowance, held so it can be handed back
    if the run is rejected before it is scheduled. `day` pins the refund to
    the UTC day the run was taken from, even if midnight passes in between."""

    device_id: str
    client_ip: str
    day: str
