"""Interfaces the application layer depends on. Infrastructure adapters
implement these structurally (Protocol = duck typing, no inheritance
required) so use cases never import a framework or a driver library."""

from typing import Awaitable, Callable, Optional, Protocol

from .entities import (
    Account,
    AccountFreeRunClaim,
    BillingAccount,
    BillingPrices,
    BillingWebhookEvent,
    ExtraRunCharge,
    SubscriptionSnapshot,
    AnalysisCompleteness,
    ApiKey,
    ApiKeyCreated,
    Capability,
    CaptionTrack,
    FreeRunClaim,
    FreeRunStatus,
    MediaVisuals,
    ReleaseIndex,
    Run,
    RunStatus,
    SavedUpload,
    SourceMetadata,
    VideoAnalysis,
    Workspace,
)
from .entitlements import MediaLimits

StageCallback = Callable[[str], Awaitable[None]]


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
        source_kind: str | None = None,
        platform: str | None = None,
        duration_seconds: float | None = None,
        media_tier: str | None = None,
        admitted_byok: bool = False,
    ) -> Run: ...

    async def get(self, run_id: str) -> Optional[Run]: ...

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]: ...

    async def set_status(self, run_id: str, status: RunStatus) -> None: ...

    async def set_stage(self, run_id: str, stage: str) -> None: ...

    async def set_result(
        self,
        run_id: str,
        result: VideoAnalysis,
        completeness: AnalysisCompleteness = AnalysisCompleteness.FULL,
    ) -> bool:
        """Mark the run complete. False when nothing was written: the run is
        gone, or it already ended (complete or failed). An ended run is
        final; every write to it is skipped, not only this one."""
        ...

    async def set_source_metadata(self, run_id: str, metadata: SourceMetadata) -> None: ...

    async def set_duration(self, run_id: str, duration_seconds: float) -> None: ...

    async def set_visuals(self, run_id: str, visuals: MediaVisuals) -> None:
        """Record the poster thumbnail and display size. Fields left None are
        left as they were."""
        ...

    async def set_error(self, run_id: str, error: str) -> bool:
        """Mark the run failed. False when the run is gone or already ended,
        as for `set_result`."""
        ...

    async def delete_for_owner(self, owner_id: str) -> int:
        """Remove every run the owner's index (or, in memory, the store)
        holds for `owner_id`, and the index itself. Returns how many runs
        were removed; an owner with none is 0, not an error."""
        ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class MediaProcessor(Protocol):
    def validate_tools(self) -> None: ...

    def create_run_dir(self, run_id: str) -> str: ...

    def cleanup_run_dir(self, run_id: str) -> None: ...

    # `limits` is the run's own (application/entitlements.py); None means
    # the deployment's standard limits.
    async def save_upload(
        self, run_id: str, upload: UploadedFile, limits: Optional[MediaLimits] = None
    ) -> SavedUpload: ...

    async def enforce_duration_cap(self, run_id: str, path: str, limits: Optional[MediaLimits] = None) -> float:
        """Probe the file, reject it if over the cap, and return the probed
        length in seconds so the caller can record it."""
        ...

    async def download_url(self, run_id: str, url: str, limits: Optional[MediaLimits] = None) -> SavedUpload: ...

    async def fetch_captions(self, url: str, limits: Optional[MediaLimits] = None) -> Optional[CaptionTrack]: ...

    async def normalize_media(self, src_path: str, run_dir: str) -> str: ...

    async def describe_visuals(
        self,
        *,
        media_path: str | None = None,
        thumbnail_urls: tuple[str, ...] = (),
        width: int | None = None,
        height: int | None = None,
        duration_seconds: float | None = None,
    ) -> MediaVisuals:
        """Poster thumbnail (a small JPEG data URL) and display size for the
        history card. `thumbnail_urls`/`width`/`height` are the source's own
        hints (yt-dlp); `media_path` is the local file, when there is one.
        Never raises: anything that goes wrong yields None fields."""
        ...


class SourceResolver(Protocol):
    """One route to the media behind a URL. Several may exist for the same
    source; the chain that owns them decides the order and moves on to the
    next when one fails."""

    @property
    def name(self) -> str: ...

    def can_handle(self, url: str) -> bool: ...

    async def fetch(self, run_id: str, url: str, limits: Optional[MediaLimits] = None) -> SavedUpload: ...


class AnalysisEngine(Protocol):
    async def analyze_with_retry(
        self,
        video_path: str,
        on_stage: Optional[StageCallback] = None,
        api_key: str | None = None,
        metadata: Optional[SourceMetadata] = None,
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
        limits: Optional[MediaLimits] = None,
    ) -> None:
        """`limits` travels with the job (never the key: that goes through
        the KeyVault), so the worker enforces what the API admitted."""
        ...

    async def close(self) -> None: ...


class LongRunGuard(Protocol):
    """At most one run above the standard media limits in flight per
    account. A slot is held by one run id; acquiring again for the same run
    succeeds (and re-arms the expiry), so intake and worker can both claim it.
    It expires on its own after a whole long job could have taken, so a dead
    worker never leaves an account locked out."""

    async def try_acquire(self, key: str, run_id: str) -> bool: ...

    async def release(self, key: str, run_id: str) -> None:
        """Free the slot if `run_id` holds it; otherwise a no-op."""
        ...

    async def close(self) -> None: ...


class SpendCap(Protocol):
    async def try_consume(self) -> bool: ...

    async def close(self) -> None: ...


class DeviceTokenSigner(Protocol):
    """Issues and checks the signed, anonymous device token the free-run
    allowance is counted against. The token carries no personal data: it is
    a random id plus a signature, so a client cannot mint ids of its own."""

    def issue(self) -> str: ...

    def verify(self, token: str) -> str | None:
        """The device id inside a genuine token, or None for anything else."""
        ...


class FreeRunAllowance(Protocol):
    """How many runs a caller without their own Gemini key may start per
    UTC day, counted per device and, as a backstop, per IP."""

    @property
    def enabled(self) -> bool: ...

    async def status(self, device_id: str) -> FreeRunStatus:
        """Read-only: never consumes."""
        ...

    async def try_consume(self, device_id: str, client_ip: str) -> FreeRunClaim | None:
        """Atomically take one run from both counters, or None (taking
        nothing) if either is already at its limit."""
        ...

    async def refund(self, claim: FreeRunClaim) -> None: ...

    async def hold(self, run_id: str, claim: FreeRunClaim) -> None:
        """Remember which free run `run_id` took, so the pipeline can hand it
        back later without the claim travelling in job arguments (arq logs
        those). Stores counter keys only, never the raw IP."""
        ...

    async def release(self, run_id: str, *, refund: bool) -> bool:
        """Forget the free run held for `run_id`, handing it back first when
        `refund` is true. Atomic and idempotent: only the first call for a
        run acts, so a run is never refunded twice. True when a run was
        handed back; False when nothing was held (BYOK, allowance off,
        already released, expired) or `refund` was false."""
        ...

    async def close(self) -> None: ...


class AccountFreeRunAllowance(Protocol):
    """How many runs a signed-in account without its own Gemini key may
    start per UTC calendar month. Replaces the device counter for that
    caller (never adds to it), so the runs follow the person across devices.
    Same hold/release contract as `FreeRunAllowance`, so the pipeline can
    hand a run back the same way."""

    @property
    def enabled(self) -> bool: ...

    async def status(self, account_id: str, *, limit: int | None = None) -> FreeRunStatus:
        """Read-only: never consumes. `scope` is ACCOUNT. `limit` overrides
        the free monthly limit (the paid plan's included runs count on the
        same counter, docs/backend/billing.md)."""
        ...

    async def try_consume(self, account_id: str, *, limit: int | None = None) -> AccountFreeRunClaim | None:
        """Atomically take one run if this month's count is below the
        limit (`limit`, else the free monthly one), or None (taking
        nothing). Concurrent calls can never take the account past it."""
        ...

    async def refund(self, claim: AccountFreeRunClaim) -> None:
        """Hand one run back to the claim's month, never below zero."""
        ...

    async def hold(self, run_id: str, claim: AccountFreeRunClaim) -> None: ...

    async def release(self, run_id: str, *, refund: bool) -> bool:
        """Forget the run held for `run_id`, refunding first when `refund`.
        Only the first call for a run acts. True when a run was handed back."""
        ...

    async def close(self) -> None: ...


class KeyVault(Protocol):
    async def store(self, run_id: str, api_key: str) -> None: ...

    async def take(self, run_id: str) -> str | None: ...

    async def close(self) -> None: ...


class TokenVerifier(Protocol):
    def decode(self, token: str) -> dict:
        """Verified claims, or raises. `AuthNotConfiguredError` (domain) when
        no identity provider is configured; anything else means the token is
        not acceptable. Synchronous: a JWKS cache miss is a network call, so
        callers run it off the event loop."""
        ...


class AccountDirectory(Protocol):
    """Accounts and workspaces: who is signed in and which workspace they
    act in. `enabled` is False on a deployment with no account store, where
    a signed-in caller is a bare `user:<sub>` principal as before accounts
    existed."""

    @property
    def enabled(self) -> bool: ...

    async def resolve_account(self, external_id: str, email: str | None = None) -> Account:
        """The account for an identity-provider subject, created (with its
        default workspace) on first sight. Keeps `email` current."""
        ...

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]: ...

    async def member_role(self, workspace_id: str, account_id: str) -> Optional[str]: ...

    async def close(self) -> None: ...


class ApiKeyRepository(Protocol):
    """A workspace's API keys. Stores a hash of each secret, never the
    secret, so a database read never yields a usable credential."""

    async def issue(
        self, workspace_id: str, name: str, scopes: list[str], *, max_active: int
    ) -> ApiKeyCreated:
        """Mint a key. Raises `ApiKeyLimitError` when the workspace already
        holds `max_active` live keys (checked in the same transaction)."""
        ...

    async def authenticate(self, secret: str) -> Optional[ApiKey]:
        """The live key this secret belongs to, or None. Records
        `last_used_at`, at most once a minute per key."""
        ...

    async def list_for_workspace(self, workspace_id: str) -> list[ApiKey]: ...

    async def revoke(self, workspace_id: str, key_id: str) -> bool:
        """True when a live key in that workspace was revoked."""
        ...

    async def close(self) -> None: ...


class IdentityProviderUsers(Protocol):
    """Whether the identity provider still has a user for a subject.

    An access token outlives its user: after `DELETE /api/me` it still
    verifies for up to an hour. Without this check that token would re-create
    the account on its next request and could mint an API key bound to a
    subject nobody can sign in as again, so nobody could ever list or revoke
    it. Asked only where rows would be created (first sight of a subject,
    key creation), never on ordinary reads.

    Stores with no identity provider to ask (SQLite, in-memory) answer True."""

    async def exists(self, external_id: str) -> bool: ...


class AccountDeleter(Protocol):
    """Removes a signed-in person for good: their identity rows, then their
    identity-provider user. Two steps on purpose, called in that order, so a
    failure after the first leaves the provider user in place and a retry
    with the same session still resolves the person. Once both steps have
    succeeded the person is gone for good: `IdentityProviderUsers` refuses
    their still-valid token (401), so there is no second deletion to make.

    `enabled` matches the account directory's: False on a deployment with no
    account store, where there is nothing to delete."""

    @property
    def enabled(self) -> bool: ...

    async def delete_account(self, external_id: str) -> bool:
        """Delete the account for this identity-provider subject with every
        workspace it owns, those workspaces' memberships and API keys, and
        its own memberships elsewhere, in one transaction. False when there
        was no such account (rows already deleted by an earlier, part-way
        attempt): not an error."""
        ...

    async def delete_identity(self, external_id: str) -> bool:
        """Delete the identity-provider user. False when this store has no
        provider to delete from (SQLite, in-memory) and the step was skipped;
        raises when the provider refused."""
        ...


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


class BillingGateway(Protocol):
    """The payment provider (Stripe). Every call is a network call; the
    application never sees a Stripe object, only the domain records.
    `enabled` is False when a required setting is blank, and every other
    method then raises `BillingNotConfiguredError`."""

    @property
    def enabled(self) -> bool: ...

    @property
    def yearly_available(self) -> bool: ...

    async def create_customer(self, account_id: str, email: str | None) -> str:
        """A new customer id. Idempotent per account for a day (Stripe
        idempotency key), so two racing checkouts make one customer."""
        ...

    async def create_checkout_session(self, *, customer_id: str, account_id: str, interval: str) -> str:
        """The hosted Checkout URL for the plan at `interval`."""
        ...

    async def create_portal_session(self, customer_id: str) -> str: ...

    async def prices(self) -> BillingPrices:
        """Cached; never raises (an unreadable price is None)."""
        ...

    def parse_webhook(self, payload: bytes, signature: str) -> BillingWebhookEvent:
        """Verify the signature and reduce the event. Raises
        `WebhookSignatureError` when it does not verify. No network."""
        ...

    async def get_subscription(self, subscription_id: str) -> SubscriptionSnapshot: ...

    async def cancel_subscription(self, subscription_id: str) -> None:
        """Cancel now, no proration credit, outstanding usage invoiced now.
        An already-cancelled subscription is not an error."""
        ...

    async def report_extra_run(self, charge: ExtraRunCharge) -> None:
        """One meter event (value 1) with the run id as its identifier, so a
        resend inside Stripe's dedup window cannot bill twice."""
        ...


class BillingAccounts(Protocol):
    """Which Stripe customer and subscription belong to which account
    (`billing_accounts`, or memory locally), plus webhook idempotency."""

    @property
    def enabled(self) -> bool: ...

    async def get(self, account_id: str) -> Optional[BillingAccount]: ...

    async def by_customer(self, customer_id: str) -> Optional[BillingAccount]: ...

    async def link_customer(self, account_id: str, customer_id: str) -> BillingAccount:
        """Record the account's customer, unless it already has one: the
        stored one wins and is returned."""
        ...

    async def apply_subscription(self, account_id: str, snapshot: SubscriptionSnapshot) -> bool:
        """Store the subscription's state on the account. False (nothing
        written) when the account has no billing row, or holds a different
        live subscription and this one is not live."""
        ...

    async def event_seen(self, event_id: str) -> bool: ...

    async def mark_event(self, event_id: str, event_type: str) -> None:
        """Record a processed event (idempotent)."""
        ...

    async def close(self) -> None: ...


class ExtraRunLedger(Protocol):
    """Runs a paid account started past its included runs, from admission
    to the Stripe report. States: held (admitted) -> due (completed) ->
    reported; held -> void (failed, refunded, rejected). Only `due` rows are
    ever reported, and each transition happens at most once."""

    async def hold(self, run_id: str, *, account_id: str, customer_id: str, period: str) -> None: ...

    async def count(self, account_id: str, period: str) -> int:
        """Extra runs not voided this period (the monthly safety cap)."""
        ...

    async def complete(self, run_id: str) -> Optional[ExtraRunCharge]:
        """held -> due. The charge when this call moved it, else None (not
        an extra run, or already settled)."""
        ...

    async def void(self, run_id: str) -> bool:
        """held -> void. True when this call voided it."""
        ...

    async def due(self, *, limit: int = 50) -> list[ExtraRunCharge]: ...

    async def mark_reported(self, run_id: str) -> None: ...
