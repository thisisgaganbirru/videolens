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


class AuthMethod(str, Enum):
    """How the caller proved who they are. `require_person` in the API layer
    accepts only TOKEN: an API key may run analyses but never manage keys."""

    ANONYMOUS = "anonymous"
    TOKEN = "token"
    API_KEY = "api_key"


@dataclass(frozen=True)
class Principal:
    """Who is calling, and on whose behalf.

    `subject` identifies the caller: `client:<X-Client-ID>` (anonymous),
    `user:<sub>` (a signed-in person's identity-provider subject) or
    `key:<key_id>` (an API key). `account_id` is set for a signed-in person
    and, for an API key, is the account that owns the key's workspace, so
    quota is per person however many keys they mint.
    """

    subject: str
    authenticated: bool
    method: AuthMethod = AuthMethod.ANONYMOUS
    account_id: Optional[str] = None
    workspace_id: Optional[str] = None
    email: Optional[str] = None

    @property
    def owner_id(self) -> str:
        """What runs are scoped to.

        The subject, in this phase. The target is the workspace
        (`workspace:<id>`), so a key and the web app see one history, but
        `CreateRunUseCase` writes `principal.subject` as a run's owner and is
        deliberately not modified in auth phase 1 (`docs/auth-plan.md`). Read
        and list go through this property via `policies.can_access_run`, so
        switching to the workspace is this line plus the one in
        `create_run.py`, together.
        """
        return self.subject


class Account(BaseModel):
    """A signed-in person. `external_id` is the identity provider's `sub`
    claim; it is the only thing a token carries, so it is what accounts are
    looked up by."""

    account_id: str
    external_id: str
    email: Optional[str] = None
    default_workspace_id: Optional[str] = None
    created_at: datetime


class WorkspaceRole(str, Enum):
    OWNER = "owner"
    MEMBER = "member"


class Workspace(BaseModel):
    """Where API keys (and, later, seats and plans) live. Every account gets
    one on first sign-in; not shown in the UI in this phase."""

    workspace_id: str
    name: str
    owner_account_id: str
    created_at: datetime


class ApiKey(BaseModel):
    """The visible half of an API key. The secret is hashed at issue time and
    never stored, so this is all a listing can ever show."""

    key_id: str
    workspace_id: str
    name: str
    # The first characters of the secret (`vl_live_` plus a few), kept so a
    # list of keys is recognisable. Not enough to authenticate with.
    prefix: str
    scopes: list[str] = Field(default_factory=lambda: ["runs:write", "runs:read"])
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True)
class ApiKeyCreated:
    """A freshly issued key together with its secret: the only moment the
    plaintext exists on the server side. Returned to the caller once."""

    key: ApiKey
    secret: str


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
