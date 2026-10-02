"""Interfaces the application layer depends on. Infrastructure adapters
implement these structurally (Protocol = duck typing, no inheritance
required) so use cases never import a framework or a driver library."""

from datetime import datetime
from decimal import Decimal
from typing import Awaitable, Callable, Optional, Protocol

from .entities import (
    Account,
    AnalysisCompleteness,
    ApiKey,
    BillingEvent,
    Capability,
    CaptionTrack,
    IssuedApiKey,
    ReleaseIndex,
    Run,
    RunStatus,
    SavedUpload,
    SourceMetadata,
    TokenUsage,
    UsageEvent,
    VideoAnalysis,
    Workspace,
)
from .entitlements import MediaResolution, Plan

StageCallback = Callable[[str], Awaitable[None]]
UsageCallback = Callable[[TokenUsage], Awaitable[None]]


class UploadedFile(Protocol):
    """Whatever the caller submitted as a file. FastAPI's UploadFile
    satisfies this structurally, without the domain importing FastAPI."""

    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...

    async def close(self) -> None: ...


class RunRepository(Protocol):
    async def create(
        self,
        run_id: str,
        owner_id: str,
        *,
        workspace_id: str | None = None,
        plan: Plan = Plan.FREE,
        max_duration_seconds: int | None = None,
        source_url: str | None = None,
    ) -> Run: ...

    async def get(self, run_id: str) -> Optional[Run]: ...

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]: ...

    async def set_duration(self, run_id: str, duration_seconds: float) -> None: ...

    async def set_usage(self, run_id: str, usage: TokenUsage) -> None: ...

    async def set_status(self, run_id: str, status: RunStatus) -> None: ...

    async def set_stage(self, run_id: str, stage: str) -> None: ...

    async def set_result(
        self,
        run_id: str,
        result: VideoAnalysis,
        completeness: AnalysisCompleteness = AnalysisCompleteness.FULL,
    ) -> None: ...

    async def set_source_metadata(self, run_id: str, metadata: SourceMetadata) -> None: ...

    async def set_error(self, run_id: str, error: str) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class MediaProcessor(Protocol):
    def validate_tools(self) -> None: ...

    def create_run_dir(self, run_id: str) -> str: ...

    def cleanup_run_dir(self, run_id: str) -> None: ...

    async def save_upload(
        self, run_id: str, upload: UploadedFile, max_size_mb: int | None = None
    ) -> SavedUpload: ...

    async def enforce_duration_cap(
        self, run_id: str, path: str, max_seconds: int | None = None
    ) -> float: ...

    async def download_url(self, run_id: str, url: str) -> SavedUpload: ...

    async def fetch_captions(self, url: str) -> Optional[CaptionTrack]: ...

    async def normalize_media(self, src_path: str, run_dir: str) -> str: ...


class SourceResolver(Protocol):
    """One route to the media behind a URL. Several may exist for the same
    source; the chain that owns them decides the order and moves on to the
    next when one fails."""

    @property
    def name(self) -> str: ...

    def can_handle(self, url: str) -> bool: ...

    async def fetch(self, run_id: str, url: str) -> SavedUpload: ...


class AnalysisEngine(Protocol):
    async def analyze_with_retry(
        self,
        video_path: str,
        on_stage: Optional[StageCallback] = None,
        api_key: str | None = None,
        metadata: Optional[SourceMetadata] = None,
        resolution: MediaResolution = MediaResolution.DEFAULT,
        on_usage: Optional[UsageCallback] = None,
    ) -> VideoAnalysis: ...

    async def analyze_captions(
        self,
        captions: CaptionTrack,
        api_key: str | None = None,
    ) -> VideoAnalysis: ...


class ObjectStore(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def upload_source(self, run_id: str, path: str) -> str: ...

    async def download_source(self, key: str, destination: str) -> None: ...

    async def delete_source(self, key: str) -> None: ...


class JobQueue(Protocol):
    async def enqueue(
        self,
        run_id: str,
        *,
        saved_path: str | None = None,
        run_dir: str | None = None,
        source_url: str | None = None,
        source_key: str | None = None,
        gemini_api_key: str | None = None,
    ) -> None: ...

    async def close(self) -> None: ...


class SpendCap(Protocol):
    async def try_consume(self) -> bool: ...

    async def close(self) -> None: ...


class KeyVault(Protocol):
    async def store(self, run_id: str, api_key: str) -> None: ...

    async def take(self, run_id: str) -> str | None: ...

    async def close(self) -> None: ...


class TokenVerifier(Protocol):
    def decode(self, token: str) -> dict: ...


class CapabilityProbe(Protocol):
    """One health check. Adapters own the knowledge of what "working"
    means for their dependency; the application layer only aggregates."""

    @property
    def name(self) -> str: ...

    async def check(self) -> Capability: ...


class ReleaseCatalog(Protocol):
    """Where the app's own release history comes from.

    A port because the answer is a GitHub read today and need not stay one:
    the frontend only needs the index, not the provider.
    """

    async def fetch(self) -> ReleaseIndex: ...


class RunArchive(Protocol):
    """Durable, searchable storage for a workspace's finished runs.

    Separate from `RunRepository` on purpose: the live store is a hot cache
    with a TTL and the archive is a system of record, and a tiered repository
    composes the two. `enabled` is False when no database is configured, in
    which case nothing is ever archived and history keeps its TTL behaviour.
    """

    @property
    def enabled(self) -> bool: ...

    async def archive(self, run: Run) -> None: ...

    async def get(self, run_id: str) -> Optional[Run]: ...

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]: ...

    async def search(
        self,
        owner_id: str,
        *,
        query: str = "",
        platform: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Run]: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class AccountDirectory(Protocol):
    """Accounts and workspaces: who is signed in, which workspace they act
    in, and what that workspace is subscribed to."""

    @property
    def enabled(self) -> bool: ...

    async def resolve_account(self, external_id: str, email: str | None = None) -> Account: ...

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]: ...

    async def get_workspace_by_customer(self, stripe_customer_id: str) -> Optional[Workspace]: ...

    async def list_workspaces(self, account_id: str) -> list[Workspace]: ...

    async def member_role(self, workspace_id: str, account_id: str) -> Optional[str]: ...

    async def set_customer(self, workspace_id: str, stripe_customer_id: str) -> None: ...

    async def apply_subscription(
        self,
        workspace_id: str,
        *,
        plan: Plan,
        minutes_included: int,
        period_start: datetime,
        period_end: datetime,
        stripe_subscription_id: str | None,
    ) -> Workspace: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class UsageMeter(Protocol):
    async def minutes_used(self, workspace_id: str, since: datetime) -> Decimal: ...

    async def record(self, event: UsageEvent) -> None: ...

    async def close(self) -> None: ...


class ApiKeyRepository(Protocol):
    async def issue(self, workspace_id: str, name: str, scopes: list[str]) -> IssuedApiKey: ...

    async def authenticate(self, secret: str) -> Optional[ApiKey]: ...

    async def list_for_workspace(self, workspace_id: str) -> list[ApiKey]: ...

    async def revoke(self, workspace_id: str, key_id: str) -> bool: ...

    async def close(self) -> None: ...


class BillingGateway(Protocol):
    """The payment provider, reduced to the four things the product needs
    from it. Stripe today; the use cases never see a Stripe type."""

    @property
    def enabled(self) -> bool: ...

    async def create_checkout_url(
        self,
        *,
        workspace: Workspace,
        plan: Plan,
        customer_email: str | None,
        success_url: str,
        cancel_url: str,
    ) -> str: ...

    async def create_portal_url(self, *, customer_id: str, return_url: str) -> str: ...

    def parse_webhook(self, payload: bytes, signature: str) -> BillingEvent: ...

    async def report_usage(self, *, customer_id: str, minutes: Decimal, run_id: str) -> str | None: ...
