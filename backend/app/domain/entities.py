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
    # The media tier the run was admitted under (`MediaTier` value). Server
    # bookkeeping, not sent to the client: it picks the staleness threshold,
    # since a signed-in + BYOK run has the longer worker timeout. None (a run
    # stored before tiers existed) reads as standard.
    media_tier: Optional[str] = None
    # True when intake admitted the run on the caller's own Gemini key, so it
    # skipped the free-run and daily-cap checks. Never the key itself. The
    # worker refuses such a run when the vault has no key for it rather than
    # spend the shared key on it (docs/backend/byok.md). Server bookkeeping,
    # not sent to the client; False for a run stored before it existed.
    admitted_byok: bool = False
    # The account the run was admitted for (a signed-in person, or the
    # account owning the API key's workspace), so the worker can save a paid
    # account's result to its server-side history once the run completes
    # (docs/backend/saved-history.md). Server bookkeeping, never sent to the
    # client; None for anonymous runs and runs stored before it existed.
    account_id: Optional[str] = None


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
    # The 30-day deletion hold (docs/backend/saved-history.md): set by
    # `DELETE /api/me`, cleared by a restore. While `purge_at` is set the
    # account is refused everywhere except `POST /api/me/restore`; once it
    # has passed, the cleanup job removes the account for good.
    deleted_at: Optional[datetime] = None
    purge_at: Optional[datetime] = None
    # Complimentary Plus (docs/backend/billing.md): on the paid plan without
    # Stripe, never billed. Set only by hand in SQL by the owner.
    complimentary_plus: bool = False

    @property
    def pending_deletion(self) -> bool:
        return self.purge_at is not None


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
    # Bytes on disk, when the adapter measured them (the one-long-run-per-
    # account guard counts a file above the standard size as long).
    size_bytes: Optional[int] = None


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


class FreeRunScope(str, Enum):
    """Which counter a caller's free runs come from. DEVICE: anonymous (and
    signed-in callers when the account allowance is off), per UTC day.
    ACCOUNT: a signed-in account, across devices: per UTC day on the free
    plan (since 2026-11-14), per UTC calendar month on the paid plan."""

    DEVICE = "device"
    ACCOUNT = "account"


class FreeRunPeriod(str, Enum):
    """How long a counter runs before it resets. DAY: a UTC day, keyed
    "YYYY-MM-DD" (the device allowance, and the free plan's account
    allowance, and since 2026-11-14 the paid plan's included runs). MONTH: a
    UTC calendar month, keyed "YYYY-MM" (the paid plan's included runs
    before 2026-11-14; still a valid key). The two key formats never
    overlap, so day and month counters can share a table without colliding."""

    DAY = "day"
    MONTH = "month"


@dataclass(frozen=True)
class FreeRunStatus:
    """Where one device (or, with `scope=ACCOUNT`, one account) stands
    against its free-run allowance.

    `used` is the device's own count; the per-IP backstop is deliberately
    not reflected here (it is not something a device can see or act on).
    `enabled=False` means there is no free-run limit at all.
    """

    enabled: bool
    limit: int
    used: int
    remaining: int
    resets_at: datetime
    scope: FreeRunScope = FreeRunScope.DEVICE
    period: FreeRunPeriod = FreeRunPeriod.DAY


@dataclass(frozen=True)
class FreeRunClaim:
    """One free run taken from the allowance, held so it can be handed back
    if the run is rejected before it is scheduled. `day` pins the refund to
    the UTC day the run was taken from, even if midnight passes in between."""

    device_id: str
    client_ip: str
    day: str


@dataclass(frozen=True)
class AccountFreeRunClaim:
    """One run taken from an account's counter. `period` is the counter's
    key: "YYYY-MM-DD" (UTC day: the free plan, and the paid plan's included
    runs) or "YYYY-MM" (UTC month, if a plan counts monthly). It pins a refund to the day or month the
    run was taken from, even if midnight or the month turns in between."""

    account_id: str
    period: str


# ------------------------------------------------------------------ billing
#
# The paid plan (docs/backend/billing.md): one Stripe subscription per
# account, monthly or yearly, with `PAID_RUNS_PER_DAY` shared-key runs
# a UTC day included and every run past them billed as one "extra run" (a Stripe
# Billing Meter event, sent only once the run completed). Amounts are never
# here: they live in Stripe Prices, read through `BillingGateway.prices`.


@dataclass(frozen=True)
class Price:
    """One Stripe Price as the client shows it: `amount` in the currency's
    minor units (cents), `currency` lower-case ISO 4217."""

    amount: int
    currency: str


@dataclass(frozen=True)
class BillingPrices:
    """The plan's three prices. Any may be None: not configured (yearly is
    optional), or Stripe could not be read just now."""

    month: Optional[Price] = None
    year: Optional[Price] = None
    extra_run: Optional[Price] = None


@dataclass(frozen=True)
class SubscriptionSnapshot:
    """A Stripe subscription reduced to what the plan check needs. Built by
    the gateway from a fresh read, so webhook ordering never matters.
    `interval` is the base price's ("month" | "year"); `account_id` is the
    one the subscription's metadata names, when it names one."""

    subscription_id: str
    customer_id: str
    status: str
    price_id: Optional[str] = None
    interval: Optional[str] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    account_id: Optional[str] = None


@dataclass(frozen=True)
class BillingAccount:
    """An account's Stripe link (`billing_accounts`): the customer, and the
    subscription it holds or last held. Subscription fields are None until a
    checkout completes."""

    account_id: str
    stripe_customer_id: str
    stripe_subscription_id: Optional[str] = None
    status: Optional[str] = None
    price_id: Optional[str] = None
    interval: Optional[str] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    updated_at: Optional[datetime] = None


@dataclass(frozen=True)
class PlanStanding:
    """Which plan an account is on right now, and why
    (`BillingPlans.standing`).

    - `subscription`: the account's billing row when a Stripe subscription
      grants the paid plan now (active or trialing, within its period plus
      the grace). Billing follows it: extra runs past the included ones are
      admitted and billed through the meter.
    - `complimentary`: on the paid plan through `accounts.complimentary_plus`
      and NOT through a paying subscription. Never billed: no extra runs,
      no ledger row, no meter event, no checkout or portal. False whenever
      `subscription` is set (the real subscription wins).

    Neither: the free plan."""

    subscription: Optional[BillingAccount] = None
    complimentary: bool = False

    @property
    def paid(self) -> bool:
        """On the paid plan ("Plus"): paid media limits, the paid plan's
        included runs, saved history."""
        return self.subscription is not None or self.complimentary

    @property
    def billable(self) -> bool:
        """Runs past the included ones may be admitted as billed extra runs."""
        return self.subscription is not None


@dataclass(frozen=True)
class BillingWebhookEvent:
    """A verified Stripe event, reduced by the gateway. Only ids: never a
    card, an address or an email. `subscription_id` is the subscription the
    event concerns (directly, or through its invoice or checkout session);
    `account_id` is the one the object's metadata / client reference names."""

    event_id: str
    type: str
    customer_id: Optional[str] = None
    subscription_id: Optional[str] = None
    account_id: Optional[str] = None


@dataclass(frozen=True)
class ExtraRunCharge:
    """A completed extra run waiting to be (or being) reported to Stripe."""

    run_id: str
    account_id: str
    stripe_customer_id: str
    completed_at: datetime


# ------------------------------------------------------------ saved history
#
# Paid accounts' run results, kept on the server (docs/backend/saved-history.md;
# owner decisions 2026-11-14). Result text, a source descriptor and the
# run's small poster thumbnail (as `Run.thumbnail`): no other media, never a
# key.


@dataclass(frozen=True)
class SavedRunSource:
    """Where a saved run came from: facts about the source, never the media.
    `source_url` is the public link a link run was made from (None for a
    file run: the server never keeps a file name)."""

    source_kind: Optional[str] = None
    platform: Optional[str] = None
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    uploader: Optional[str] = None
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> dict:
        return {key: value for key, value in self.__dict__.items() if value is not None}

    @classmethod
    def from_dict(cls, data: dict | None) -> "SavedRunSource":
        data = data or {}
        return cls(**{key: data.get(key) for key in cls.__dataclass_fields__})


@dataclass(frozen=True)
class SavedRunSummary:
    """One row of the saved-history list: no transcript, no notes."""

    run_id: str
    title: str
    summary_snippet: Optional[str]
    source: SavedRunSource
    completeness: str
    created_at: datetime
    # The keyset cursor's tie-breaker (the row's own uuid).
    saved_id: str = ""
    # The poster exactly as the live run's `thumbnail`: a <=20 KB
    # `data:image/jpeg;base64,...` URL, or None when the run had none.
    thumbnail: Optional[str] = None


@dataclass(frozen=True)
class SavedRun:
    """A saved run in full. `result` is a `VideoAnalysis` as a dict (title,
    summary, transcript, on-screen text, notes, and their segments)."""

    run_id: str
    account_id: str
    title: str
    summary_snippet: Optional[str]
    source: SavedRunSource
    result: dict
    completeness: str
    created_at: datetime
    saved_id: str = ""
    thumbnail: Optional[str] = None


@dataclass(frozen=True)
class PendingAccountPurge:
    """An account whose deletion hold has ended, for the cleanup job."""

    account_id: str
    external_id: str


@dataclass(frozen=True)
class SavedRunCursor:
    """Keyset position: list rows strictly older than this one."""

    created_at: datetime
    saved_id: str


@dataclass(frozen=True)
class SavedRunPage:
    items: list
    next_cursor: Optional[SavedRunCursor] = None


@dataclass(frozen=True)
class SavedHistoryStatus:
    """Whether new runs are being saved (`saving`: the account is on the
    paid plan now) and, once the paid plan ended, when the saved runs are
    removed for good (`expires_at`). Both off for a free account that never
    paid, and on a deployment with no database or billing."""

    saving: bool = False
    expires_at: Optional[datetime] = None
