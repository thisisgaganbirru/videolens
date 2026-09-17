from datetime import datetime
from typing import Optional

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


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    title: Optional[str] = None
    created_at: datetime


class RunListResponse(BaseModel):
    runs: list[RunSummary]


class UsageResponse(BaseModel):
    plan: str
    minutes_included: int
    minutes_used: float
    minutes_remaining: float
    period_start: datetime
    period_end: datetime
    max_duration_seconds: int
    overage_usd_per_minute: Optional[float] = None


class WorkspaceResponse(BaseModel):
    workspace_id: str
    name: str
    plan: str
    seats: int
    has_subscription: bool


class AccountResponse(BaseModel):
    """`GET /api/me`. Everything the account panel renders, and nothing that
    would let one workspace learn about another."""

    subject: str
    method: str
    email: Optional[str] = None
    account_id: Optional[str] = None
    workspace: Optional[WorkspaceResponse] = None
    usage: UsageResponse
    billing_enabled: bool
    accounts_enabled: bool
    api_access: bool
    library: bool


class CheckoutRequest(BaseModel):
    plan: str


class CheckoutResponse(BaseModel):
    url: str


class ApiKeyCreateRequest(BaseModel):
    name: str = ""


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    prefix: str
    scopes: list[str]
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    # Shown once. The server keeps only a hash.
    secret: str


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyResponse]


class LibraryEntry(BaseModel):
    run_id: str
    status: RunStatus
    title: Optional[str] = None
    summary: Optional[str] = None
    platform: Optional[str] = None
    source_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    completeness: AnalysisCompleteness = AnalysisCompleteness.FULL
    created_at: datetime


class LibraryResponse(BaseModel):
    runs: list[LibraryEntry]
    query: str
    limit: int
    offset: int
