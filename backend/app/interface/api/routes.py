from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from starlette.requests import Request

from ...container import container
from ...domain.entities import ApiKey, CapabilityReport, Principal, ReleaseIndex, Run
from ...domain.run_facts import describe_run
from .dependencies import get_principal, get_signed_in_principal, require_person
from .rate_limiter import client_ip, limiter
from .schemas import (
    AccountResponse,
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyListResponse,
    ApiKeyResponse,
    EntitlementResponse,
    FreeRunsResponse,
    RunCreateResponse,
    RunListResponse,
    RunStatusResponse,
    RunSummary,
    WorkspaceResponse,
)

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/api/readiness")
async def readiness() -> dict:
    try:
        redis_ready = await container.run_repository.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Run storage is unavailable.") from exc
    return {
        "status": "ready",
        "mode": "distributed" if container.settings.queue_enabled else "local",
        "redis": redis_ready,
        "object_storage": container.object_store.enabled,
    }


@router.get("/api/capabilities", response_model=CapabilityReport)
async def capabilities() -> CapabilityReport:
    """Per-dependency health, deliberately separate from `/api/readiness`.

    Readiness answers one yes/no question for the platform's health check and
    must stay cheap; this answers "which parts work, and was that actually
    checked" for humans, the UI, and MCP clients deciding whether a run is
    worth submitting. It always returns 200 - a non-ok body is the payload,
    not an error.
    """
    return await container.get_capabilities_use_case.execute()


@router.get("/api/releases", response_model=ReleaseIndex)
async def releases() -> ReleaseIndex:
    """The app's own release history, read server-side.

    Exists because the repository is private: a browser calling GitHub's API
    gets a 404 and a token cannot ship in client-side JavaScript. Reading it
    here is what lets CI stop committing a static manifest back into the repo.
    """
    return await container.get_releases_use_case.execute()


# The read endpoints get their own, looser limit: they spend no Gemini budget,
# but each is a Redis round trip, and GET /api/free-runs also mints a device
# token for any caller that sends none. Per IP (same key as run creation).
_READ_LIMIT = f"{container.settings.read_rate_limit_per_minute}/minute"
_READS_LIMITED = container.settings.read_rate_limit_per_minute > 0


@router.get("/api/free-runs", response_model=FreeRunsResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def free_runs(request: Request) -> FreeRunsResponse:
    """Today's free-run standing for this device. Never spends a run, and
    needs no X-Client-ID: it is the first call a fresh install makes."""
    token, status = await container.get_free_runs_use_case.execute(request.headers.get("x-device-token"))
    return FreeRunsResponse(
        device_token=token,
        enabled=status.enabled,
        limit=status.limit,
        used=status.used,
        remaining=status.remaining,
        resets_at=status.resets_at,
    )


@router.post("/api/runs", response_model=RunCreateResponse, status_code=202)
@limiter.limit(f"{container.settings.rate_limit_per_hour}/hour")
async def create_run(
    request: Request,
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    accept_terms: bool = Form(default=False),
    principal: Principal = Depends(get_principal),
) -> RunCreateResponse:
    gemini_api_key = request.headers.get("x-gemini-api-key", "").strip() or None
    run = await container.create_run_use_case.execute(
        principal=principal,
        accept_terms=accept_terms,
        file=file,
        url=url,
        gemini_api_key=gemini_api_key,
        device_token=request.headers.get("x-device-token"),
        client_ip=client_ip(request),
    )
    return RunCreateResponse(run_id=run.run_id, status=run.status)


@router.get("/api/runs", response_model=RunListResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def list_runs(
    request: Request,
    principal: Principal = Depends(get_principal),
) -> RunListResponse:
    runs = await container.list_runs_use_case.execute(principal)
    return RunListResponse(runs=[_summary(run) for run in runs])


def _summary(run: Run) -> RunSummary:
    facts = describe_run(run)
    return RunSummary(
        run_id=run.run_id,
        status=run.status,
        title=run.result.title if run.result else None,
        created_at=run.created_at,
        source_kind=facts.source_kind,
        platform=facts.platform,
        duration_seconds=facts.duration_seconds,
        summary_snippet=facts.summary_snippet,
        orientation=facts.orientation,
        width=facts.width,
        height=facts.height,
    )


@router.get("/api/runs/{run_id}", response_model=RunStatusResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def get_run(
    request: Request,
    run_id: str,
    principal: Principal = Depends(get_principal),
) -> RunStatusResponse:
    run = await container.get_run_use_case.execute(run_id, principal)
    facts = describe_run(run)
    return RunStatusResponse(
        run_id=run.run_id,
        status=run.status,
        stage=run.stage,
        result=run.result,
        source_metadata=run.source_metadata,
        completeness=run.completeness,
        error=run.error,
        source_kind=facts.source_kind,
        platform=facts.platform,
        duration_seconds=facts.duration_seconds,
        thumbnail=run.thumbnail,
        width=facts.width,
        height=facts.height,
        orientation=facts.orientation,
    )


@router.get("/api/me", response_model=AccountResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def me(request: Request, principal: Principal = Depends(get_signed_in_principal)) -> AccountResponse:
    """Who the caller is and what they may do. Any authenticated caller (a
    signed-in person or an API key, so an agent can check its key); an
    anonymous caller gets 401 and reads limits from `/api/capabilities`."""
    view = await container.get_account_use_case.execute(principal)
    entitlement = view.entitlement
    return AccountResponse(
        subject=principal.subject,
        method=principal.method.value,
        email=principal.email,
        account_id=principal.account_id,
        workspace=WorkspaceResponse(workspace_id=view.workspace.workspace_id, name=view.workspace.name)
        if view.workspace
        else None,
        entitlement=EntitlementResponse(
            plan=entitlement.plan.value,
            max_duration_seconds=entitlement.max_duration_seconds,
            max_file_size_mb=entitlement.max_file_size_mb,
            metered=entitlement.metered,
            api_access=entitlement.api_access,
            library=entitlement.library,
        ),
        accounts_enabled=view.accounts_enabled,
    )


def _api_key_response(key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        key_id=key.key_id,
        name=key.name,
        prefix=key.prefix,
        scopes=key.scopes,
        active=key.active,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        created_at=key.created_at,
    )


# Key management needs a signed-in person (`require_person`): anonymous is
# 401 and an API key is 403, so a leaked agent key cannot mint more keys.
@router.get("/api/keys", response_model=ApiKeyListResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def list_api_keys(request: Request, principal: Principal = Depends(require_person)) -> ApiKeyListResponse:
    keys = await container.list_api_keys_use_case.execute(principal)
    return ApiKeyListResponse(keys=[_api_key_response(key) for key in keys])


@router.post("/api/keys", response_model=ApiKeyCreatedResponse, status_code=201)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def create_api_key(
    request: Request,
    body: ApiKeyCreateRequest,
    principal: Principal = Depends(require_person),
) -> ApiKeyCreatedResponse:
    created = await container.create_api_key_use_case.execute(principal, body.name)
    return ApiKeyCreatedResponse(**_api_key_response(created.key).model_dump(), secret=created.secret)


@router.delete("/api/keys/{key_id}", status_code=204)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def revoke_api_key(
    request: Request,
    key_id: str,
    principal: Principal = Depends(require_person),
) -> Response:
    await container.revoke_api_key_use_case.execute(principal, key_id)
    return Response(status_code=204)
