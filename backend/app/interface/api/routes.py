from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from starlette.requests import Request

from ...container import container
from ...application.saved_history import encode_cursor
from ...domain.entities import (
    ApiKey,
    BillingPrices,
    CapabilityReport,
    Price,
    Principal,
    ReleaseIndex,
    Run,
    SavedHistoryStatus,
    SavedRunSource,
)
from ...domain.errors import WebhookSignatureError
from ...domain.run_facts import describe_run
from .dependencies import (
    get_optional_signed_in_principal,
    get_principal,
    get_signed_in_principal,
    require_person,
    require_person_even_if_deleted,
)
from .rate_limiter import client_ip, limiter
from .schemas import (
    AccountDeletionResponse,
    AccountResponse,
    AccountRestoreResponse,
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyListResponse,
    ApiKeyResponse,
    BillingExtraRunsResponse,
    BillingPricesResponse,
    BillingResponse,
    BillingRunsResponse,
    BillingUrlResponse,
    CheckoutRequest,
    EntitlementResponse,
    FreeRunsResponse,
    LimitsResponse,
    MediaLimitsResponse,
    PriceResponse,
    RunCreateResponse,
    RunListResponse,
    RunStatusResponse,
    RunSummary,
    SavedHistoryResponse,
    SavedRunListResponse,
    SavedRunResponse,
    SavedRunsDeletedResponse,
    SavedRunSourceResponse,
    SavedRunSummaryResponse,
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


@router.get("/api/free-runs", response_model=FreeRunsResponse, response_model_exclude_none=True)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def free_runs(
    request: Request, principal: Principal | None = Depends(get_optional_signed_in_principal)
) -> FreeRunsResponse:
    """Free-run standing: this device's for today, or, with a valid bearer
    (JWT or API key) and the account allowance on, the account's for today
    (`scope`; the paid plan's included runs for today). `period` says
    "day" or "month" and is always sent. Never spends a run, and needs no X-Client-ID: it is the
    first call a fresh install makes. An invalid bearer is a 401."""
    # Signed in, also `plan` and `overage` (docs/backend/billing.md); on the
    # paid plan `limit` is the plan's included runs. Anonymous callers get
    # exactly the fields they always did.
    standing = await container.get_free_runs_use_case.standing(request.headers.get("x-device-token"), principal)
    status = standing.status
    return FreeRunsResponse(
        device_token=standing.device_token,
        enabled=status.enabled,
        scope=status.scope.value,
        period=status.period.value,
        limit=status.limit,
        used=status.used,
        remaining=status.remaining,
        resets_at=status.resets_at,
        plan=standing.plan,
        overage=standing.overage if standing.plan is not None else None,
    )


@router.get("/api/limits", response_model=LimitsResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def limits(request: Request, response: Response) -> LimitsResponse:
    """The media limits per caller, from settings, so the client can say
    "up to 10:00 when signed in with your own key" without hard-coding it.
    No auth: the same answer for everyone. Cacheable briefly; its own
    `Cache-Control` wins over the security headers' `no-store` default."""
    resolver = container.entitlements
    response.headers["Cache-Control"] = "public, max-age=300"
    return LimitsResponse(
        standard=MediaLimitsResponse(
            max_duration_seconds=resolver.standard.max_duration_seconds,
            max_file_size_mb=resolver.standard.max_file_size_mb,
        ),
        signed_in_byok=MediaLimitsResponse(
            max_duration_seconds=resolver.signed_in_byok.max_duration_seconds,
            max_file_size_mb=resolver.signed_in_byok.max_file_size_mb,
        ),
        # Listed whether or not billing is on: the paid plan's own numbers.
        paid=MediaLimitsResponse(
            max_duration_seconds=resolver.paid.max_duration_seconds,
            max_file_size_mb=resolver.paid.max_file_size_mb,
        ),
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
        saved_history=_saved_history(view.saved_history),
    )


def _saved_history(status: SavedHistoryStatus) -> SavedHistoryResponse:
    return SavedHistoryResponse(saving=status.saving, expires_at=status.expires_at)


@router.delete("/api/me", response_model=AccountDeletionResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def delete_me(request: Request, principal: Principal = Depends(require_person)) -> AccountDeletionResponse:
    """Delete the signed-in person's account: a 30-day hold
    (docs/backend/saved-history.md). Any subscription is cancelled now and
    the account stops working at once (every endpoint answers 410
    `account_pending_deletion`, its API keys 401); signing in again before
    `purge_at` can restore it, after it the worker removes everything and
    the Supabase user for good. A signed-in session only (`require_person`:
    anonymous 401, API key 403); 503 without an account store."""
    purge_at = await container.delete_account_use_case.execute(principal)
    return AccountDeletionResponse(purge_at=purge_at)


@router.post("/api/me/restore", response_model=AccountRestoreResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def restore_me(
    request: Request, principal: Principal = Depends(require_person_even_if_deleted)
) -> AccountRestoreResponse:
    """Take an account back out of the deletion hold: the one endpoint a
    held account may call. Everything returns (keys, saved runs) on the
    free plan. `restored: false` when it was not held; 410
    `restore_window_closed` once the hold has ended."""
    restored = await container.restore_account_use_case.execute(principal)
    return AccountRestoreResponse(restored=restored)


# ----------------------------------------------------------- saved history
# docs/backend/saved-history.md. A paid account's results, saved by the
# worker; a signed-in session only (`require_person`), always the caller's
# own account. Readable and deletable in the post-cancel window too.


def _source(source: SavedRunSource) -> SavedRunSourceResponse:
    kind = source.source_kind if source.source_kind in ("link", "file") else None
    return SavedRunSourceResponse(**{**source.to_dict(), "source_kind": kind})


@router.get("/api/history", response_model=SavedRunListResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def list_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=200),
    principal: Principal = Depends(require_person),
) -> SavedRunListResponse:
    """The caller's saved runs, newest first, light fields only. A free
    account that never paid gets `items: []` and `saving: false`; in the
    post-cancel window `expires_at` says when they go."""
    queries = container.saved_history_queries
    status = await queries.status(principal)
    page = await queries.list(principal, limit=limit, cursor=cursor)
    return SavedRunListResponse(
        saving=status.saving,
        expires_at=status.expires_at,
        items=[
            SavedRunSummaryResponse(
                run_id=item.run_id,
                title=item.title,
                summary_snippet=item.summary_snippet,
                completeness=item.completeness,
                created_at=item.created_at,
                source=_source(item.source),
                thumbnail=item.thumbnail,
            )
            for item in page.items
        ],
        next_cursor=encode_cursor(page.next_cursor),
    )


@router.get("/api/history/{run_id}", response_model=SavedRunResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def get_history_run(
    request: Request, run_id: str, principal: Principal = Depends(require_person)
) -> SavedRunResponse:
    """One saved run in full (transcript, notes, on-screen text). 404 when
    the caller's account has no saved run with that id."""
    saved = await container.saved_history_queries.get(principal, run_id)
    return SavedRunResponse(
        run_id=saved.run_id,
        title=saved.title,
        summary_snippet=saved.summary_snippet,
        completeness=saved.completeness,
        created_at=saved.created_at,
        source=_source(saved.source),
        thumbnail=saved.thumbnail,
        result=saved.result,
    )


@router.delete("/api/history/{run_id}", status_code=204)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def delete_history_run(request: Request, run_id: str, principal: Principal = Depends(require_person)) -> Response:
    await container.saved_history_queries.delete(principal, run_id)
    return Response(status_code=204)


@router.delete("/api/history", response_model=SavedRunsDeletedResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def delete_history(request: Request, principal: Principal = Depends(require_person)) -> SavedRunsDeletedResponse:
    deleted = await container.saved_history_queries.delete_all(principal)
    return SavedRunsDeletedResponse(deleted=deleted)


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


# ---------------------------------------------------------------- billing
# docs/backend/billing.md. Stripe-hosted Checkout and Customer Portal: the
# API only hands out their URLs and learns the outcome from the webhook.


def _price(price: Price | None) -> PriceResponse | None:
    return PriceResponse(amount=price.amount, currency=price.currency) if price is not None else None


def _prices(prices: BillingPrices | None) -> BillingPricesResponse:
    prices = prices or BillingPrices()
    return BillingPricesResponse(
        month=_price(prices.month), year=_price(prices.year), extra_run=_price(prices.extra_run)
    )


@router.get("/api/billing", response_model=BillingResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def billing(request: Request, principal: Principal = Depends(get_signed_in_principal)) -> Response:
    """The caller's plan and its runs (today's, on either plan). Anonymous is 401; with billing off (or no account store) just `{"enabled": false}`. Prices are
    read from Stripe (cached) and are null when Stripe could not be read."""
    view = await container.get_billing_use_case.execute(principal)
    if not view.enabled:
        return JSONResponse({"enabled": False})
    return BillingResponse(
        enabled=True,
        plan=view.plan,
        status=view.status,
        interval=view.interval if view.interval in ("month", "year") else None,
        current_period_end=view.current_period_end,
        cancel_at_period_end=view.cancel_at_period_end,
        runs=BillingRunsResponse(limit=view.runs_limit, used=view.runs_used, period=view.runs_period),
        extra_runs=(
            BillingExtraRunsResponse(
                used=view.extra_runs.used,
                limit=view.extra_runs.limit,
                period=view.extra_runs.period,
                resets_at=view.extra_runs.resets_at,
            )
            if view.extra_runs is not None
            else None
        ),
        prices=_prices(view.prices),
    )


@router.post("/api/billing/checkout", response_model=BillingUrlResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def billing_checkout(
    request: Request, body: CheckoutRequest, principal: Principal = Depends(require_person)
) -> BillingUrlResponse:
    """A Stripe Checkout URL for the paid plan. A signed-in session only
    (an API key is 403). 409 `already_subscribed` when the account already
    holds a live subscription: send the person to the portal instead."""
    url = await container.start_checkout_use_case.execute(principal, body.interval)
    return BillingUrlResponse(url=url)


@router.post("/api/billing/portal", response_model=BillingUrlResponse)
@limiter.limit(_READ_LIMIT, exempt_when=lambda: not _READS_LIMITED)
async def billing_portal(request: Request, principal: Principal = Depends(require_person)) -> BillingUrlResponse:
    """A Stripe Customer Portal URL (cancel, card, invoices). 404
    `no_billing_account` for an account that never started a checkout."""
    url = await container.open_billing_portal_use_case.execute(principal)
    return BillingUrlResponse(url=url)


# Stripe's events are a few KB; anything far bigger is not from Stripe.
_WEBHOOK_MAX_BYTES = 1024 * 1024


@router.post("/api/billing/webhook")
@limiter.exempt
async def billing_webhook(request: Request, stripe_signature: str = Header(default="")) -> dict:
    """Stripe's webhook. No auth and no rate limit: the signature
    (`STRIPE_WEBHOOK_SECRET`) is the authentication, verified against the
    raw body before anything in it is read. Idempotent per event id; a
    handling failure is a 5xx so Stripe retries. Only ids are logged."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > _WEBHOOK_MAX_BYTES:
        raise WebhookSignatureError("Payload too large.")
    payload = await request.body()
    if len(payload) > _WEBHOOK_MAX_BYTES:
        raise WebhookSignatureError("Payload too large.")
    # The use case logs the event id and outcome.
    await container.handle_billing_webhook_use_case.execute(payload, stripe_signature)
    return {"received": True}
