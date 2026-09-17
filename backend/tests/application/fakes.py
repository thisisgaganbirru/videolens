"""In-memory test doubles for the domain ports. Each fake implements exactly
the Protocol methods application-layer tests need, plus a bit of call
tracking so tests can assert on how a use case drove its dependencies."""

from datetime import datetime, timezone
from decimal import Decimal

from app.domain.entities import (
    Account,
    AnalysisCompleteness,
    ApiKey,
    BillingEvent,
    BillingEventKind,
    CaptionTrack,
    IssuedApiKey,
    Run,
    RunStatus,
    SavedUpload,
    SourceMetadata,
    TokenUsage,
    UsageEvent,
    Workspace,
)
from app.application.entitlements import EntitlementResolver
from app.domain.entitlements import MediaResolution, Plan
from app.domain.errors import BillingNotConfiguredError


class FakeRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}
        self.created_ids: list[str] = []

    async def create(
        self,
        run_id: str,
        owner_id: str,
        *,
        workspace_id: str | None = None,
        plan: Plan = Plan.FREE,
        max_duration_seconds: int | None = None,
        source_url: str | None = None,
    ) -> Run:
        now = datetime.now(timezone.utc)
        run = Run(
            run_id=run_id,
            owner_id=owner_id,
            status=RunStatus.QUEUED,
            created_at=now,
            updated_at=now,
            workspace_id=workspace_id,
            plan=plan,
            max_duration_seconds=max_duration_seconds,
            source_url=source_url,
        )
        self.runs[run_id] = run
        self.created_ids.append(run_id)
        return run

    async def set_duration(self, run_id: str, duration_seconds: float) -> None:
        self.runs[run_id].duration_seconds = duration_seconds

    async def set_usage(self, run_id: str, usage: TokenUsage) -> None:
        self.runs[run_id].usage = usage

    async def get(self, run_id: str):
        return self.runs.get(run_id)

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]:
        matches = [run for run in self.runs.values() if run.owner_id == owner_id]
        return matches[:limit]

    async def set_status(self, run_id: str, status: RunStatus) -> None:
        self.runs[run_id].status = status

    async def set_stage(self, run_id: str, stage: str) -> None:
        self.runs[run_id].stage = stage

    async def set_result(
        self, run_id: str, result, completeness=AnalysisCompleteness.FULL
    ) -> None:
        self.runs[run_id].status = RunStatus.COMPLETE
        self.runs[run_id].result = result
        self.runs[run_id].completeness = completeness

    async def set_source_metadata(self, run_id: str, metadata: SourceMetadata) -> None:
        self.runs[run_id].source_metadata = metadata

    async def set_error(self, run_id: str, error: str) -> None:
        self.runs[run_id].status = RunStatus.FAILED
        self.runs[run_id].error = error

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class FakeMediaProcessor:
    def __init__(self) -> None:
        self.validated = False
        self.cleaned_up: list[str] = []
        self.enforced_duration: list[tuple[str, str]] = []
        self.enforced_limits: list[int | None] = []
        self.duration_seconds: float = 42.0
        self.download_calls: list[tuple[str, str]] = []
        self.normalize_calls: list[tuple[str, str]] = []
        self.save_upload_error: Exception | None = None
        self.enforce_duration_error: Exception | None = None
        self.download_error: Exception | None = None
        self.download_metadata: SourceMetadata | None = None
        self.captions: CaptionTrack | None = None
        self.caption_calls: list[str] = []
        self.captions_error: Exception | None = None

    def validate_tools(self) -> None:
        self.validated = True

    def create_run_dir(self, run_id: str) -> str:
        return f"/tmp/{run_id}"

    def cleanup_run_dir(self, run_id: str) -> None:
        self.cleaned_up.append(run_id)

    async def save_upload(self, run_id: str, upload, max_size_mb: int | None = None) -> SavedUpload:
        self.upload_limits_mb: list[int | None] = getattr(self, "upload_limits_mb", [])
        self.upload_limits_mb.append(max_size_mb)
        if self.save_upload_error:
            raise self.save_upload_error
        return SavedUpload(path=f"/tmp/{run_id}/upload.mp4", run_dir=f"/tmp/{run_id}")

    async def enforce_duration_cap(
        self, run_id: str, path: str, max_seconds: int | None = None
    ) -> float:
        self.enforced_duration.append((run_id, path))
        self.enforced_limits.append(max_seconds)
        if self.enforce_duration_error:
            raise self.enforce_duration_error
        return self.duration_seconds

    async def download_url(self, run_id: str, url: str) -> SavedUpload:
        self.download_calls.append((run_id, url))
        if self.download_error:
            raise self.download_error
        return SavedUpload(
            path=f"/tmp/{run_id}/download.mp4", run_dir=f"/tmp/{run_id}", metadata=self.download_metadata
        )

    async def fetch_captions(self, url: str) -> CaptionTrack | None:
        self.caption_calls.append(url)
        if self.captions_error:
            raise self.captions_error
        return self.captions

    async def normalize_media(self, src_path: str, run_dir: str) -> str:
        self.normalize_calls.append((src_path, run_dir))
        return f"{run_dir}/normalized.mp4"


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

    async def enqueue(
        self,
        run_id: str,
        *,
        saved_path: str | None = None,
        run_dir: str | None = None,
        source_url: str | None = None,
        source_key: str | None = None,
        gemini_api_key: str | None = None,
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
        self.resolutions_seen: list[MediaResolution] = []
        self.usage: TokenUsage | None = TokenUsage(input_tokens=1200, output_tokens=300)

    async def analyze_with_retry(
        self,
        video_path: str,
        on_stage=None,
        api_key: str | None = None,
        metadata: SourceMetadata | None = None,
        resolution: MediaResolution = MediaResolution.DEFAULT,
        on_usage=None,
    ):
        self.calls.append((video_path, api_key))
        self.metadata_seen.append(metadata)
        self.resolutions_seen.append(resolution)
        if on_usage and self.usage is not None:
            await on_usage(self.usage)
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeAccountDirectory:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self.accounts: dict[str, Account] = {}
        self.workspaces: dict[str, Workspace] = {}
        self.members: dict[tuple[str, str], str] = {}
        self.subscriptions: list[dict] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def add_workspace(self, workspace: Workspace, members: dict[str, str] | None = None) -> None:
        self.workspaces[workspace.workspace_id] = workspace
        self.members[(workspace.workspace_id, workspace.owner_account_id)] = "owner"
        for account_id, role in (members or {}).items():
            self.members[(workspace.workspace_id, account_id)] = role

    async def resolve_account(self, external_id: str, email: str | None = None) -> Account:
        for account in self.accounts.values():
            if account.external_id == external_id:
                return account
        account_id = f"acct-{len(self.accounts) + 1}"
        workspace_id = f"ws-{len(self.workspaces) + 1}"
        now = _now()
        account = Account(
            account_id=account_id,
            external_id=external_id,
            email=email,
            default_workspace_id=workspace_id,
            created_at=now,
        )
        self.accounts[account_id] = account
        self.add_workspace(
            Workspace(
                workspace_id=workspace_id,
                name="Personal",
                owner_account_id=account_id,
                plan=Plan.FREE,
                minutes_included=30,
                period_start=now,
                period_end=now,
                created_at=now,
            )
        )
        return account

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        return self.workspaces.get(workspace_id)

    async def get_workspace_by_customer(self, stripe_customer_id: str) -> Workspace | None:
        for workspace in self.workspaces.values():
            if workspace.stripe_customer_id == stripe_customer_id:
                return workspace
        return None

    async def list_workspaces(self, account_id: str) -> list[Workspace]:
        return [
            workspace
            for workspace in self.workspaces.values()
            if (workspace.workspace_id, account_id) in self.members
        ]

    async def member_role(self, workspace_id: str, account_id: str) -> str | None:
        return self.members.get((workspace_id, account_id))

    async def set_customer(self, workspace_id: str, stripe_customer_id: str) -> None:
        self.workspaces[workspace_id].stripe_customer_id = stripe_customer_id

    async def apply_subscription(
        self,
        workspace_id: str,
        *,
        plan: Plan,
        minutes_included: int,
        period_start: datetime,
        period_end: datetime,
        stripe_subscription_id: str | None,
    ) -> Workspace:
        workspace = self.workspaces[workspace_id]
        workspace.plan = plan
        workspace.minutes_included = minutes_included
        workspace.period_start = period_start
        workspace.period_end = period_end
        workspace.stripe_subscription_id = stripe_subscription_id
        self.subscriptions.append(dict(workspace_id=workspace_id, plan=plan))
        return workspace

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class FakeUsageMeter:
    def __init__(self) -> None:
        self.events: list[UsageEvent] = []
        self.preloaded: dict[str, Decimal] = {}

    async def minutes_used(self, workspace_id: str, since: datetime) -> Decimal:
        total = self.preloaded.get(workspace_id, Decimal("0"))
        for event in self.events:
            if event.workspace_id == workspace_id and event.created_at >= since:
                total += event.minutes_billed
        return total

    async def record(self, event: UsageEvent) -> None:
        self.events.append(event)

    async def close(self) -> None:
        pass


class FakeApiKeyRepository:
    def __init__(self) -> None:
        self.keys: dict[str, ApiKey] = {}
        self.secrets: dict[str, str] = {}

    async def issue(self, workspace_id: str, name: str, scopes: list[str]) -> IssuedApiKey:
        key_id = f"key-{len(self.keys) + 1}"
        secret = f"vl_live_{key_id}_secret"
        key = ApiKey(
            key_id=key_id,
            workspace_id=workspace_id,
            name=name,
            prefix=f"vl_live_{key_id}",
            scopes=scopes,
            created_at=_now(),
        )
        self.keys[key_id] = key
        self.secrets[secret] = key_id
        return IssuedApiKey(key=key, secret=secret)

    async def authenticate(self, secret: str) -> ApiKey | None:
        key_id = self.secrets.get(secret)
        if key_id is None:
            return None
        key = self.keys[key_id]
        return key if key.active else None

    async def list_for_workspace(self, workspace_id: str) -> list[ApiKey]:
        return [key for key in self.keys.values() if key.workspace_id == workspace_id]

    async def revoke(self, workspace_id: str, key_id: str) -> bool:
        key = self.keys.get(key_id)
        if key is None or key.workspace_id != workspace_id or not key.active:
            return False
        key.revoked_at = _now()
        return True

    async def close(self) -> None:
        pass


class FakeBillingGateway:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self.checkouts: list[dict] = []
        self.portals: list[dict] = []
        self.reported: list[dict] = []
        self.next_event: BillingEvent = BillingEvent(kind=BillingEventKind.IGNORED, event_id="evt-0")

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def create_checkout_url(self, *, workspace, plan, customer_email, success_url, cancel_url) -> str:
        if not self._enabled:
            raise BillingNotConfiguredError("Billing is not configured.")
        self.checkouts.append(dict(workspace_id=workspace.workspace_id, plan=plan, email=customer_email))
        return f"https://checkout.example/{workspace.workspace_id}/{plan.value}"

    async def create_portal_url(self, *, customer_id: str, return_url: str) -> str:
        if not self._enabled:
            raise BillingNotConfiguredError("Billing is not configured.")
        self.portals.append(dict(customer_id=customer_id, return_url=return_url))
        return f"https://portal.example/{customer_id}"

    def parse_webhook(self, payload: bytes, signature: str) -> BillingEvent:
        return self.next_event

    async def report_usage(self, *, customer_id: str, minutes: Decimal, run_id: str) -> str | None:
        self.reported.append(dict(customer_id=customer_id, minutes=minutes, run_id=run_id))
        return f"meter-{run_id}"


def make_entitlements(
    accounts=None, usage=None, default_max_duration_seconds: int = 180
) -> EntitlementResolver:
    return EntitlementResolver(
        accounts=accounts or FakeAccountDirectory(enabled=False),
        usage=usage or FakeUsageMeter(),
        default_max_duration_seconds=default_max_duration_seconds,
    )


def make_workspace(
    workspace_id: str = "ws-pro",
    owner_account_id: str = "acct-1",
    plan: Plan = Plan.PRO,
    **overrides,
) -> Workspace:
    now = _now()
    fields = dict(
        workspace_id=workspace_id,
        name="Team",
        owner_account_id=owner_account_id,
        plan=plan,
        minutes_included=600 if plan is not Plan.FREE else 30,
        period_start=now,
        period_end=now,
        created_at=now,
    )
    fields.update(overrides)
    return Workspace(**fields)


class FakeRunArchive:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self.archived: list[Run] = []
        self.searches: list[dict] = []
        self.results: list[Run] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def archive(self, run: Run) -> None:
        self.archived.append(run)

    async def get(self, run_id: str) -> Run | None:
        return next((run for run in self.archived if run.run_id == run_id), None)

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]:
        return [run for run in self.archived if run.owner_id == owner_id][:limit]

    async def search(self, owner_id: str, *, query, platform, since, until, limit, offset) -> list[Run]:
        self.searches.append(
            dict(
                owner_id=owner_id,
                query=query,
                platform=platform,
                since=since,
                until=until,
                limit=limit,
                offset=offset,
            )
        )
        return list(self.results)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass
