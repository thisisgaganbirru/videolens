from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .entitlements import Plan


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


class TokenUsage(BaseModel):
    """What one Gemini call consumed, as the API reported it back.

    Kept on the run (and on the usage event) so the margin on a plan is a
    query, not an estimate: the per-minute cost table in `entitlements.py` is
    a forecast, these are the numbers the invoice will actually be made of.
    """

    input_tokens: int = 0
    output_tokens: int = 0


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
    # Everything below is absent on an anonymous run and on any run stored
    # before workspaces existed - every default is the pre-workspace
    # behaviour, so old Redis entries still validate.
    workspace_id: Optional[str] = None
    plan: Plan = Plan.FREE
    # The cap this run was admitted under. Carried on the run rather than
    # re-derived in the worker so a plan change mid-run cannot fail a run
    # that was legitimately accepted, and so the worker needs no billing
    # lookup at all. None means the deployment-wide default.
    max_duration_seconds: Optional[int] = None
    source_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    usage: Optional[TokenUsage] = None


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
    ANONYMOUS = "anonymous"
    TOKEN = "token"
    API_KEY = "api_key"


@dataclass(frozen=True)
class Principal:
    """Who is calling, and on whose behalf.

    `subject` identifies the caller (`client:<id>`, `user:<sub>`); `owner_id`
    is what runs are scoped to. They differ once a caller belongs to a
    workspace: two seats on the same Studio plan share a library, so runs are
    owned by the workspace, not the seat. Without a workspace - anonymous use,
    or a signed-in caller before any workspace exists - the two are the same
    string, which is exactly the pre-workspace behaviour.
    """

    subject: str
    authenticated: bool
    method: AuthMethod = AuthMethod.ANONYMOUS
    account_id: Optional[str] = None
    workspace_id: Optional[str] = None
    plan: Plan = Plan.FREE
    email: Optional[str] = None

    @property
    def owner_id(self) -> str:
        return f"workspace:{self.workspace_id}" if self.workspace_id else self.subject


class WorkspaceRole(str, Enum):
    OWNER = "owner"
    MEMBER = "member"


class Account(BaseModel):
    """A signed-in person. `external_id` is the identity provider's subject
    claim (Clerk's user id today); it is the only thing the token carries, so
    it is what accounts are looked up by."""

    account_id: str
    external_id: str
    email: Optional[str] = None
    default_workspace_id: Optional[str] = None
    created_at: datetime


class Workspace(BaseModel):
    workspace_id: str
    name: str
    owner_account_id: str
    plan: Plan = Plan.FREE
    seats: int = 1
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    minutes_included: int = 0
    minutes_used_period: Decimal = Decimal("0")
    period_start: datetime
    period_end: datetime
    # Per-workspace override of the plan's cap, for a hand-negotiated deal.
    # None means the plan's own number applies.
    max_duration_seconds: Optional[int] = None
    created_at: datetime


class UsageSummary(BaseModel):
    """The one number a person on a paid plan asks about, with its context."""

    plan: Plan
    minutes_included: int
    minutes_used: Decimal
    period_start: datetime
    period_end: datetime
    max_duration_seconds: int
    overage_usd_per_minute: Optional[Decimal] = None

    @property
    def minutes_remaining(self) -> Decimal:
        return max(Decimal(self.minutes_included) - self.minutes_used, Decimal("0"))


class UsageEvent(BaseModel):
    event_id: str
    workspace_id: str
    run_id: str
    minutes_billed: Decimal
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate_usd: Decimal = Decimal("0")
    meter_event_id: Optional[str] = None
    created_at: datetime


class ApiKey(BaseModel):
    """The visible half of an API key. The secret is hashed at issue time and
    never stored, so this is all a listing can ever show."""

    key_id: str
    workspace_id: str
    name: str
    prefix: str
    scopes: list[str] = Field(default_factory=lambda: ["runs:write", "runs:read"])
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True)
class IssuedApiKey:
    """A freshly created key together with its secret - the only moment the
    secret exists in plaintext on the server side."""

    key: ApiKey
    secret: str


class BillingEventKind(str, Enum):
    SUBSCRIPTION_STARTED = "subscription_started"
    SUBSCRIPTION_UPDATED = "subscription_updated"
    SUBSCRIPTION_ENDED = "subscription_ended"
    IGNORED = "ignored"


class BillingEvent(BaseModel):
    """A billing provider's webhook, reduced to what the application acts on.

    Provider-specific shape stays in the adapter: the use case that applies
    this never learns that "customer.subscription.updated" is a Stripe string.
    """

    kind: BillingEventKind
    event_id: str
    customer_id: Optional[str] = None
    subscription_id: Optional[str] = None
    workspace_id: Optional[str] = None
    plan: Optional[Plan] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


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
