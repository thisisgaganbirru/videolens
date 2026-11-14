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


class MediaLimitsResponse(BaseModel):
    max_duration_seconds: int
    max_file_size_mb: int


class LimitsResponse(BaseModel):
    """`GET /api/limits`. The media-limit sets: `standard` for everyone,
    `signed_in_byok` for a signed-in caller who sends their own Gemini key,
    `paid` for a paid-plan account (with or without a key;
    docs/backend/billing.md)."""

    standard: MediaLimitsResponse
    signed_in_byok: MediaLimitsResponse
    paid: MediaLimitsResponse


class FreeRunsResponse(BaseModel):
    """`device_token` is always present: the one sent, if it was genuine,
    else a newly issued one the client should store and send back as
    `X-Device-Token`. `enabled=False` means no free-run limit applies.
    `scope` says which counter the numbers are: "device" or "account" (a
    signed-in account). `period` says how long it runs (since 2026-11-14):
    "day" (UTC; the device, and a free account) or "month" (UTC calendar
    month; the paid plan's included runs). `resets_at` is its end.

    Signed in only (left out for anonymous callers, so their response is
    unchanged): `plan` "free" or "paid"; `overage` true on the paid plan,
    where runs past `limit` are billed as extra runs instead of refused."""

    device_token: str
    enabled: bool
    scope: str = "device"
    period: Literal["day", "month"] = "day"
    limit: int
    used: int
    remaining: int
    resets_at: datetime
    plan: Optional[Literal["free", "paid"]] = None
    overage: Optional[bool] = None


class PriceResponse(BaseModel):
    """An amount in the currency's smallest unit (cents), as Stripe has it."""

    amount: int
    currency: str


class BillingPricesResponse(BaseModel):
    month: Optional[PriceResponse] = None
    year: Optional[PriceResponse] = None
    extra_run: Optional[PriceResponse] = None


class BillingRunsResponse(BaseModel):
    """`period`: "day" (free plan, since 2026-11-14) or "month" (paid)."""

    limit: int
    used: int
    period: Literal["day", "month"] = "month"


class BillingResponse(BaseModel):
    """`GET /api/billing`. With billing off only `{"enabled": false}` is
    sent (every other field is left out)."""

    enabled: bool
    plan: Optional[Literal["free", "paid"]] = None
    status: Optional[str] = None
    interval: Optional[Literal["month", "year"]] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None
    runs: Optional[BillingRunsResponse] = None
    prices: Optional[BillingPricesResponse] = None


class CheckoutRequest(BaseModel):
    interval: Literal["month", "year"] = "month"


class BillingUrlResponse(BaseModel):
    """A Stripe-hosted page to send the browser to."""

    url: str


class RunListResponse(BaseModel):
    runs: list[RunSummary]


class WorkspaceResponse(BaseModel):
    workspace_id: str
    name: str


class EntitlementResponse(BaseModel):
    """What the caller may do. One plan (`free`) in this phase; the numbers
    are the deployment's own limits."""

    plan: str
    max_duration_seconds: int
    max_file_size_mb: int
    metered: bool
    api_access: bool
    library: bool


class AccountResponse(BaseModel):
    """`GET /api/me`. Identity and entitlement, no usage. Kept separate from
    the domain entities so nothing internal (key hashes, other members)
    can leak through a new field."""

    subject: str
    method: str
    email: Optional[str] = None
    account_id: Optional[str] = None
    workspace: Optional[WorkspaceResponse] = None
    entitlement: EntitlementResponse
    # False on a deployment with no account store: sign-in still works, but
    # there is nowhere to keep API keys.
    accounts_enabled: bool


class ApiKeyCreateRequest(BaseModel):
    name: str = ""


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    prefix: str
    scopes: list[str]
    active: bool
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    # Shown once. The server keeps only its hash.
    secret: str


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyResponse]
