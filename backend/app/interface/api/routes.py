from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from starlette.requests import Request

from ...container import container
from ...domain.entities import ApiKey, CapabilityReport, Principal, ReleaseIndex, Run
from ...domain.entitlements import Plan, entitlement_for
from .dependencies import get_principal, get_signed_in_principal
from .rate_limiter import limiter
from .schemas import (
    AccountResponse,
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyListResponse,
    ApiKeyResponse,
    CheckoutRequest,
    CheckoutResponse,
    LibraryEntry,
    LibraryResponse,
    RunCreateResponse,
    RunListResponse,
    RunStatusResponse,
    RunSummary,
    UsageResponse,
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
    )
    return RunCreateResponse(run_id=run.run_id, status=run.status)


@router.get("/api/runs", response_model=RunListResponse)
async def list_runs(
    principal: Principal = Depends(get_principal),
) -> RunListResponse:
    runs = await container.list_runs_use_case.execute(principal)
    return RunListResponse(
        runs=[
            RunSummary(
                run_id=run.run_id,
                status=run.status,
                title=run.result.title if run.result else None,
                created_at=run.created_at,
            )
            for run in runs
        ]
    )


@router.get("/api/runs/{run_id}", response_model=RunStatusResponse)
async def get_run(
    run_id: str,
    principal: Principal = Depends(get_principal),
) -> RunStatusResponse:
    run = await container.get_run_use_case.execute(run_id, principal)
    return RunStatusResponse(
        run_id=run.run_id,
        status=run.status,
        stage=run.stage,
        result=run.result,
        source_metadata=run.source_metadata,
        completeness=run.completeness,
        error=run.error,
    )


@router.get("/api/library", response_model=LibraryResponse)
async def library(
    query: str = Query(default="", max_length=200),
    platform: str | None = Query(default=None, max_length=64),
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(get_principal),
) -> LibraryResponse:
    """Search across everything the caller has analyzed.

    Anonymous callers get a title match over their recent history; a
    workspace with durable storage gets full-text search over every run it
    has ever completed. Same endpoint, same shape, so the library tab needs
    no branching.
    """
    runs = await container.search_library_use_case.execute(
        principal, query=query, platform=platform, since=since, until=until, limit=limit, offset=offset
    )
    return LibraryResponse(
        runs=[_library_entry(run) for run in runs], query=query.strip(), limit=limit, offset=offset
    )


def _library_entry(run: Run) -> LibraryEntry:
    return LibraryEntry(
        run_id=run.run_id,
        status=run.status,
        title=run.result.title if run.result else (run.source_metadata.title if run.source_metadata else None),
        summary=run.result.summary if run.result else None,
        platform=run.source_metadata.platform if run.source_metadata else None,
        source_url=run.source_url or (run.source_metadata.source_url if run.source_metadata else None),
        duration_seconds=run.duration_seconds,
        completeness=run.completeness,
        created_at=run.created_at,
    )


@router.get("/api/me", response_model=AccountResponse)
async def me(principal: Principal = Depends(get_principal)) -> AccountResponse:
    """Who the caller is and what their plan allows. Works for anonymous
    callers too - it is how the frontend learns the deployment's limits."""
    view = await container.get_account_use_case.execute(principal)
    entitlement = entitlement_for(view.usage.plan)
    usage = view.usage
    return AccountResponse(
        subject=principal.subject,
        method=principal.method.value,
        email=principal.email,
        account_id=principal.account_id,
        workspace=WorkspaceResponse(
            workspace_id=view.workspace.workspace_id,
            name=view.workspace.name,
            plan=view.workspace.plan.value,
            seats=view.workspace.seats,
            has_subscription=bool(view.workspace.stripe_subscription_id),
        )
        if view.workspace
        else None,
        usage=UsageResponse(
            plan=usage.plan.value,
            minutes_included=usage.minutes_included,
            minutes_used=float(usage.minutes_used),
            minutes_remaining=float(usage.minutes_remaining),
            period_start=usage.period_start,
            period_end=usage.period_end,
            max_duration_seconds=usage.max_duration_seconds,
            overage_usd_per_minute=float(usage.overage_usd_per_minute)
            if usage.overage_usd_per_minute is not None
            else None,
        ),
        billing_enabled=view.billing_enabled,
        accounts_enabled=view.accounts_enabled,
        api_access=entitlement.api_access,
        library=entitlement.library,
    )


@router.post("/api/billing/checkout", response_model=CheckoutResponse)
async def billing_checkout(
    body: CheckoutRequest,
    principal: Principal = Depends(get_signed_in_principal),
) -> CheckoutResponse:
    try:
        plan = Plan(body.plan.strip().lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown plan.") from exc
    origin = container.settings.frontend_origin
    url = await container.start_checkout_use_case.execute(
        principal,
        plan,
        success_url=f"{origin}/?view=account&checkout=success",
        cancel_url=f"{origin}/?view=account&checkout=cancelled",
    )
    return CheckoutResponse(url=url)


@router.post("/api/billing/portal", response_model=CheckoutResponse)
async def billing_portal(principal: Principal = Depends(get_signed_in_principal)) -> CheckoutResponse:
    origin = container.settings.frontend_origin
    url = await container.open_billing_portal_use_case.execute(
        principal, return_url=f"{origin}/?view=account"
    )
    return CheckoutResponse(url=url)


@router.post("/api/webhooks/stripe", status_code=200)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default=""),
) -> Response:
    """Stripe's webhook. Deliberately outside `get_principal`: the caller is
    Stripe, authenticated by the signature over the raw body, which is why
    the body is read as bytes and never parsed by FastAPI first."""
    payload = await request.body()
    await container.apply_billing_event_use_case.execute(payload, stripe_signature)
    return Response(status_code=200)


def _api_key_response(key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        key_id=key.key_id,
        name=key.name,
        prefix=key.prefix,
        scopes=key.scopes,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        created_at=key.created_at,
    )


@router.get("/api/keys", response_model=ApiKeyListResponse)
async def list_api_keys(principal: Principal = Depends(get_signed_in_principal)) -> ApiKeyListResponse:
    keys = await container.manage_api_keys_use_case.list(principal)
    return ApiKeyListResponse(keys=[_api_key_response(key) for key in keys])


@router.post("/api/keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: ApiKeyCreateRequest,
    principal: Principal = Depends(get_signed_in_principal),
) -> ApiKeyCreatedResponse:
    issued = await container.manage_api_keys_use_case.issue(principal, body.name)
    return ApiKeyCreatedResponse(**_api_key_response(issued.key).model_dump(), secret=issued.secret)


@router.delete("/api/keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    principal: Principal = Depends(get_signed_in_principal),
) -> Response:
    await container.manage_api_keys_use_case.revoke(principal, key_id)
    return Response(status_code=204)
