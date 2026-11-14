"""In-memory test doubles for the domain ports. Each fake implements exactly
the Protocol methods application-layer tests need, plus a bit of call
tracking so tests can assert on how a use case drove its dependencies."""

from datetime import datetime, timezone

from app.domain.entities import (
    AccountFreeRunClaim,
    AnalysisCompleteness,
    CaptionTrack,
    FreeRunClaim,
    FreeRunPeriod,
    FreeRunScope,
    FreeRunStatus,
    MediaVisuals,
    Run,
    RunStatus,
    SavedUpload,
    SourceMetadata,
)


class FakeRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}
        self.created_ids: list[str] = []
        self.set_visuals_error: Exception | None = None
        self.visuals_written_while: list[RunStatus] = []
        self.deleted_owners: list[str] = []
        self.delete_error: Exception | None = None
        # Writes refused because the run was gone or had already ended.
        self.skipped_writes: list[str] = []
        # Awaited once, just before the next set_result (a race in a test).
        self.before_result = None

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
    ) -> Run:
        now = datetime.now(timezone.utc)
        run = Run(
            run_id=run_id,
            owner_id=owner_id,
            status=RunStatus.QUEUED,
            created_at=now,
            updated_at=now,
            source_kind=source_kind,
            platform=platform,
            duration_seconds=duration_seconds,
            media_tier=media_tier,
            admitted_byok=admitted_byok,
        )
        self.runs[run_id] = run
        self.created_ids.append(run_id)
        return run

    async def get(self, run_id: str):
        return self.runs.get(run_id)

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]:
        matches = [run for run in self.runs.values() if run.owner_id == owner_id]
        return matches[:limit]

    async def delete_for_owner(self, owner_id: str) -> int:
        self.deleted_owners.append(owner_id)
        if self.delete_error is not None:
            raise self.delete_error
        doomed = [run_id for run_id, run in self.runs.items() if run.owner_id == owner_id]
        for run_id in doomed:
            del self.runs[run_id]
        return len(doomed)

    def _live(self, run_id: str) -> Run | None:
        # Like RunStore: a missing or ended (complete/failed) run is never
        # written again.
        run = self.runs.get(run_id)
        if run is None or run.status in (RunStatus.COMPLETE, RunStatus.FAILED):
            self.skipped_writes.append(run_id)
            return None
        return run

    async def set_status(self, run_id: str, status: RunStatus) -> None:
        if (run := self._live(run_id)) is not None:
            run.status = status

    async def set_stage(self, run_id: str, stage: str) -> None:
        if (run := self._live(run_id)) is not None:
            run.stage = stage

    async def set_result(
        self, run_id: str, result, completeness=AnalysisCompleteness.FULL
    ) -> bool:
        if self.before_result is not None:
            hook, self.before_result = self.before_result, None
            await hook()
        if (run := self._live(run_id)) is None:
            return False
        run.status = RunStatus.COMPLETE
        run.result = result
        run.completeness = completeness
        return True

    async def set_source_metadata(self, run_id: str, metadata: SourceMetadata) -> None:
        if (run := self._live(run_id)) is not None:
            run.source_metadata = metadata

    async def set_duration(self, run_id: str, duration_seconds: float) -> None:
        if (run := self._live(run_id)) is not None:
            run.duration_seconds = duration_seconds

    async def set_visuals(self, run_id: str, visuals: MediaVisuals) -> None:
        if self.set_visuals_error:
            raise self.set_visuals_error
        run = self._live(run_id)
        if run is None:
            return
        # Visuals land before the status flips: record what the run looked like.
        self.visuals_written_while.append(run.status)
        run.thumbnail = visuals.thumbnail
        run.width = visuals.width
        run.height = visuals.height

    async def set_error(self, run_id: str, error: str) -> bool:
        if (run := self._live(run_id)) is None:
            return False
        run.status = RunStatus.FAILED
        run.error = error
        return True

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class FakeMediaProcessor:
    def __init__(self) -> None:
        self.validated = False
        self.cleaned_up: list[str] = []
        self.enforced_duration: list[tuple[str, str]] = []
        self.download_calls: list[tuple[str, str]] = []
        self.normalize_calls: list[tuple[str, str]] = []
        self.normalize_error: Exception | None = None
        self.save_upload_error: Exception | None = None
        self.enforce_duration_error: Exception | None = None
        self.probed_duration: float = 42.5
        self.upload_extension: str = ".mp4"
        self.download_error: Exception | None = None
        self.download_metadata: SourceMetadata | None = None
        self.captions: CaptionTrack | None = None
        self.caption_calls: list[str] = []
        self.captions_error: Exception | None = None
        self.download_thumbnail_urls: tuple[str, ...] = ()
        self.download_dims: tuple[int | None, int | None] = (None, None)
        self.visuals = MediaVisuals(thumbnail="data:image/jpeg;base64,AAAA", width=1280, height=720)
        self.visuals_error: BaseException | None = None
        self.visuals_calls: list[dict] = []
        # The MediaLimits each call was given, per method, in call order.
        self.limits_seen: dict[str, list] = {}
        self.upload_size_bytes: int | None = None
        self.download_size_bytes: int | None = None

    def _saw(self, method: str, limits) -> None:
        self.limits_seen.setdefault(method, []).append(limits)

    def validate_tools(self) -> None:
        self.validated = True

    def create_run_dir(self, run_id: str) -> str:
        return f"/tmp/{run_id}"

    def cleanup_run_dir(self, run_id: str) -> None:
        self.cleaned_up.append(run_id)

    async def save_upload(self, run_id: str, upload, limits=None) -> SavedUpload:
        self._saw("save_upload", limits)
        if self.save_upload_error:
            raise self.save_upload_error
        return SavedUpload(
            path=f"/tmp/{run_id}/upload{self.upload_extension}",
            run_dir=f"/tmp/{run_id}",
            size_bytes=self.upload_size_bytes,
        )

    async def enforce_duration_cap(self, run_id: str, path: str, limits=None) -> float:
        self._saw("enforce_duration_cap", limits)
        self.enforced_duration.append((run_id, path))
        if self.enforce_duration_error:
            raise self.enforce_duration_error
        return self.probed_duration

    async def download_url(self, run_id: str, url: str, limits=None) -> SavedUpload:
        self._saw("download_url", limits)
        self.download_calls.append((run_id, url))
        if self.download_error:
            raise self.download_error
        return SavedUpload(
            path=f"/tmp/{run_id}/download.mp4",
            run_dir=f"/tmp/{run_id}",
            metadata=self.download_metadata,
            thumbnail_urls=self.download_thumbnail_urls,
            width=self.download_dims[0],
            height=self.download_dims[1],
            size_bytes=self.download_size_bytes,
        )

    async def fetch_captions(self, url: str, limits=None) -> CaptionTrack | None:
        self._saw("fetch_captions", limits)
        self.caption_calls.append(url)
        if self.captions_error:
            raise self.captions_error
        return self.captions

    async def normalize_media(self, src_path: str, run_dir: str) -> str:
        self.normalize_calls.append((src_path, run_dir))
        if self.normalize_error:
            raise self.normalize_error
        return f"{run_dir}/normalized.mp4"

    async def describe_visuals(self, **kwargs) -> MediaVisuals:
        self.visuals_calls.append(kwargs)
        if self.visuals_error:
            raise self.visuals_error
        return self.visuals


class FakeObjectStore:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self.uploaded: dict[str, str] = {}
        self.downloaded: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.upload_source_error: Exception | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def upload_source(self, run_id: str, path: str) -> str:
        if self.upload_source_error:
            raise self.upload_source_error
        key = f"runs/{run_id}/source.mp4"
        self.uploaded[run_id] = key
        return key

    async def download_source(self, key: str, destination: str) -> None:
        self.downloaded.append((key, destination))

    async def delete_source(self, key: str) -> None:
        self.deleted.append(key)


class RaisingObjectStore(FakeObjectStore):
    """An object store whose delete_source always fails - used to prove
    ProcessRunUseCase's cleanup doesn't get short-circuited by it."""

    async def delete_source(self, key: str) -> None:
        raise RuntimeError("S3 is down")


class FakeJobQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []
        self.closed = False
        self.enqueue_error: Exception | None = None
        self.enqueued_limits: list = []

    async def enqueue(
        self,
        run_id: str,
        *,
        saved_path: str | None = None,
        run_dir: str | None = None,
        source_url: str | None = None,
        source_key: str | None = None,
        gemini_api_key: str | None = None,
        limits=None,
    ) -> None:
        if self.enqueue_error:
            raise self.enqueue_error
        self.enqueued.append(
            dict(
                run_id=run_id,
                saved_path=saved_path,
                run_dir=run_dir,
                source_url=source_url,
                source_key=source_key,
                gemini_api_key=gemini_api_key,
            )
        )
        self.enqueued_limits.append(limits)

    async def close(self) -> None:
        self.closed = True


class FakeSpendCap:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.consume_calls = 0

    async def try_consume(self) -> bool:
        self.consume_calls += 1
        return self.allow

    async def close(self) -> None:
        pass


class FakeAnalysisEngine:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str | None]] = []
        self.stages_seen: list[str] = []
        self.metadata_seen: list[SourceMetadata | None] = []
        self.caption_calls: list[CaptionTrack] = []
        self.caption_result = None
        self.caption_error: Exception | None = None

    async def analyze_with_retry(
        self,
        video_path: str,
        on_stage=None,
        api_key: str | None = None,
        metadata: SourceMetadata | None = None,
    ):
        self.calls.append((video_path, api_key))
        self.metadata_seen.append(metadata)
        if on_stage:
            await on_stage("uploading_to_gemini")
            self.stages_seen.append("uploading_to_gemini")
            await on_stage("analyzing")
            self.stages_seen.append("analyzing")
        if self.error:
            raise self.error
        return self.result

    async def analyze_captions(self, captions, api_key: str | None = None):
        self.caption_calls.append(captions)
        if self.caption_error:
            raise self.caption_error
        return self.caption_result or self.result


class FakeUploadedFile:
    def __init__(self, filename: str = "upload.mp4") -> None:
        self.filename = filename
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        return b""

    async def close(self) -> None:
        self.closed = True


class FakeDeviceTokens:
    """Accepts "good:<device id>" tokens and nothing else."""

    def __init__(self) -> None:
        self.issued = 0

    def issue(self) -> str:
        self.issued += 1
        return f"good:device-{self.issued}"

    def verify(self, token: str) -> str | None:
        return token.removeprefix("good:") if token.startswith("good:") else None


class FakeFreeRunAllowance:
    """Counts per device and per IP like the real adapter, minus the days."""

    def __init__(self, *, enabled: bool = True, per_device: int = 3, per_ip: int = 10) -> None:
        self._enabled = enabled
        self.per_device = per_device
        self.per_ip = per_ip
        self.device_counts: dict[str, int] = {}
        self.ip_counts: dict[str, int] = {}
        self.consume_calls = 0
        self.refunds: list[FreeRunClaim] = []
        self.held: dict[str, FreeRunClaim] = {}
        self.release_calls: list[tuple[str, bool]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def status(self, device_id: str) -> FreeRunStatus:
        used = self.device_counts.get(device_id, 0)
        return FreeRunStatus(
            enabled=self._enabled,
            limit=self.per_device,
            used=used,
            remaining=max(0, self.per_device - used),
            resets_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
        )

    async def try_consume(self, device_id: str, client_ip: str) -> FreeRunClaim | None:
        self.consume_calls += 1
        if self.device_counts.get(device_id, 0) >= self.per_device:
            return None
        if self.ip_counts.get(client_ip, 0) >= self.per_ip:
            return None
        self.device_counts[device_id] = self.device_counts.get(device_id, 0) + 1
        self.ip_counts[client_ip] = self.ip_counts.get(client_ip, 0) + 1
        return FreeRunClaim(device_id=device_id, client_ip=client_ip, day="2026-11-01")

    async def refund(self, claim: FreeRunClaim) -> None:
        self.refunds.append(claim)
        self.device_counts[claim.device_id] -= 1
        self.ip_counts[claim.client_ip] -= 1

    async def hold(self, run_id: str, claim: FreeRunClaim) -> None:
        self.held[run_id] = claim

    async def release(self, run_id: str, *, refund: bool) -> bool:
        self.release_calls.append((run_id, refund))
        claim = self.held.pop(run_id, None)
        if claim is None or not refund:
            return False
        await self.refund(claim)
        return True

    async def close(self) -> None:
        pass


class FakeAccountFreeRunAllowance:
    """Per account per counter key, like the real adapters: `day` for the
    free plan's daily counter, `month` for a monthly one (the paid plan).
    Set either to move to another day or month."""

    def __init__(
        self, *, enabled: bool = True, limit: int = 10, day: str = "2026-11-14", month: str = "2026-11"
    ) -> None:
        self._enabled = enabled
        self.limit = limit
        self.day = day
        self.month = month
        self.counts: dict[tuple[str, str], int] = {}
        self.consume_calls = 0
        self.consume_limits: list[int | None] = []
        self.consume_periods: list[FreeRunPeriod] = []
        self.refunds: list[AccountFreeRunClaim] = []
        self.held: dict[str, AccountFreeRunClaim] = {}
        self.release_calls: list[tuple[str, bool]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def key(self, period: FreeRunPeriod = FreeRunPeriod.DAY) -> str:
        return self.day if period is FreeRunPeriod.DAY else self.month

    def used(self, account_id: str, period: FreeRunPeriod = FreeRunPeriod.DAY) -> int:
        return self.counts.get((account_id, self.key(period)), 0)

    async def status(
        self, account_id: str, *, limit: int | None = None, period: FreeRunPeriod = FreeRunPeriod.DAY
    ) -> FreeRunStatus:
        used = self.used(account_id, period)
        limit = self.limit if limit is None else limit
        resets_at = (
            datetime(2026, 11, 15, tzinfo=timezone.utc)
            if period is FreeRunPeriod.DAY
            else datetime(2026, 12, 1, tzinfo=timezone.utc)
        )
        return FreeRunStatus(
            enabled=self._enabled or limit != self.limit,
            limit=limit,
            used=min(used, limit),
            remaining=max(0, limit - used),
            resets_at=resets_at,
            scope=FreeRunScope.ACCOUNT,
            period=period,
        )

    async def try_consume(
        self, account_id: str, *, limit: int | None = None, period: FreeRunPeriod = FreeRunPeriod.DAY
    ) -> AccountFreeRunClaim | None:
        self.consume_calls += 1
        self.consume_limits.append(limit)
        self.consume_periods.append(period)
        key = (account_id, self.key(period))
        if self.counts.get(key, 0) >= (self.limit if limit is None else limit):
            return None
        self.counts[key] = self.counts.get(key, 0) + 1
        return AccountFreeRunClaim(account_id=account_id, period=key[1])

    async def refund(self, claim: AccountFreeRunClaim) -> None:
        self.refunds.append(claim)
        key = (claim.account_id, claim.period)
        if self.counts.get(key, 0) > 0:
            self.counts[key] -= 1

    async def hold(self, run_id: str, claim: AccountFreeRunClaim) -> None:
        self.held[run_id] = claim

    async def release(self, run_id: str, *, refund: bool) -> bool:
        self.release_calls.append((run_id, refund))
        claim = self.held.pop(run_id, None)
        if claim is None or not refund:
            return False
        await self.refund(claim)
        return True

    async def close(self) -> None:
        pass


class FakeTokenVerifier:
    """Returns fixed claims, or raises `error` (an AuthNotConfiguredError, or
    anything else for a token that does not verify)."""

    def __init__(self, claims: dict | None = None, error: Exception | None = None) -> None:
        self.claims = claims if claims is not None else {"sub": "user-123", "role": "authenticated"}
        self.error = error
        self.tokens: list[str] = []

    def decode(self, token: str) -> dict:
        self.tokens.append(token)
        if self.error is not None:
            raise self.error
        return dict(self.claims)


class FakeIdentityProviderUsers:
    """Every subject exists unless it is in `gone`. `asked` records each
    lookup, so a test can pin that reads of existing accounts never ask."""

    def __init__(self, gone: set[str] | None = None) -> None:
        self.gone = gone if gone is not None else set()
        self.asked: list[str] = []

    async def exists(self, external_id: str) -> bool:
        self.asked.append(external_id)
        return external_id not in self.gone


class FakeAccountDeleter:
    """Records each step into `log` (shared with the test, so the order of
    run deletion against these two steps can be asserted). `rows_exist` is
    what `delete_account` reports; `identity_supported` is False for a store
    with no identity provider (SQLite, in-memory)."""

    def __init__(
        self,
        log: list[str] | None = None,
        *,
        enabled: bool = True,
        rows_exist: bool = True,
        identity_supported: bool = True,
    ) -> None:
        self.log = log if log is not None else []
        self._enabled = enabled
        self.rows_exist = rows_exist
        self.identity_supported = identity_supported
        self.rows_error: Exception | None = None
        self.identity_error: Exception | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def delete_account(self, external_id: str) -> bool:
        self.log.append(f"rows:{external_id}")
        if self.rows_error is not None:
            raise self.rows_error
        return self.rows_exist

    async def delete_identity(self, external_id: str) -> bool:
        self.log.append(f"identity:{external_id}")
        if self.identity_error is not None:
            raise self.identity_error
        return self.identity_supported


class FakeLongRunGuard:
    """LongRunGuard double: one slot per key, same-run re-acquire succeeds."""

    def __init__(self) -> None:
        self.holders: dict[str, str] = {}
        self.acquire_calls: list[tuple[str, str]] = []
        self.release_calls: list[tuple[str, str]] = []

    async def try_acquire(self, key: str, run_id: str) -> bool:
        self.acquire_calls.append((key, run_id))
        holder = self.holders.get(key)
        if holder is not None and holder != run_id:
            return False
        self.holders[key] = run_id
        return True

    async def release(self, key: str, run_id: str) -> None:
        self.release_calls.append((key, run_id))
        if self.holders.get(key) == run_id:
            del self.holders[key]

    async def close(self) -> None:
        pass


class FakeBillingGateway:
    """BillingGateway double. `subscriptions` is what Stripe would return
    per subscription id; `events` maps a signature to the event it verifies
    as (anything else raises WebhookSignatureError, like a bad signature).
    Set `error` to make the network calls fail like Stripe being down."""

    def __init__(self, *, enabled: bool = True, yearly: bool = True) -> None:
        from app.domain.entities import BillingPrices, Price

        self._enabled = enabled
        self._yearly = yearly
        self.customers: list[str] = []
        self.checkouts: list[dict] = []
        self.portals: list[str] = []
        self.subscriptions: dict = {}
        self.events: dict = {}
        self.cancelled: list[str] = []
        self.reported: list = []
        self.error: Exception | None = None
        self.report_error: Exception | None = None
        self.cancel_error: Exception | None = None
        self.price_list = BillingPrices(
            month=Price(amount=1200, currency="usd"),
            year=Price(amount=12000, currency="usd") if yearly else None,
            extra_run=Price(amount=15, currency="usd"),
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def yearly_available(self) -> bool:
        return self._yearly

    def _fail(self) -> None:
        if self.error is not None:
            raise self.error

    async def create_customer(self, account_id: str, email: str | None) -> str:
        self._fail()
        customer_id = f"cus_{account_id}"
        self.customers.append(customer_id)
        return customer_id

    async def create_checkout_session(self, *, customer_id: str, account_id: str, interval: str) -> str:
        self._fail()
        self.checkouts.append({"customer_id": customer_id, "account_id": account_id, "interval": interval})
        return f"https://checkout.stripe.test/{customer_id}/{interval}"

    async def create_portal_session(self, customer_id: str) -> str:
        self._fail()
        self.portals.append(customer_id)
        return f"https://billing.stripe.test/{customer_id}"

    async def prices(self):
        return self.price_list

    def parse_webhook(self, payload: bytes, signature: str):
        from app.domain.errors import WebhookSignatureError

        if signature not in self.events:
            raise WebhookSignatureError("Invalid signature.")
        return self.events[signature]

    async def get_subscription(self, subscription_id: str):
        self._fail()
        return self.subscriptions[subscription_id]

    async def cancel_subscription(self, subscription_id: str) -> None:
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancelled.append(subscription_id)

    async def report_extra_run(self, charge) -> None:
        if self.report_error is not None:
            raise self.report_error
        self.reported.append(charge.run_id)
