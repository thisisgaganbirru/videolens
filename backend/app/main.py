import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request

from .budget import daily_budget
from .config import settings
from .logging_config import configure_logging
from .models import RunCreateResponse, RunListResponse, RunStatusResponse, RunSummary
from .queue import close_queue, enqueue_run
from .rate_limit import limiter
from .runs import run_store
from .security import Principal, get_principal
from .storage import delete_source, upload_source
from .video import (
    MediaValidationError,
    cleanup_run_dir,
    enforce_duration_cap,
    save_upload,
    validate_media_tools,
)

configure_logging()
logger = logging.getLogger(__name__)
os.makedirs(settings.temp_dir, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    validate_media_tools()
    if settings.queue_enabled:
        await run_store.ping()
        if not settings.object_storage_enabled:
            raise RuntimeError("S3-compatible object storage is required when Redis queueing is enabled.")
        if settings.allowed_origins.strip() == "*":
            logger.warning(
                "ALLOWED_ORIGINS is \"*\" in a distributed deployment (REDIS_URL is set). "
                "Any website can call this API from a browser. Set ALLOWED_ORIGINS to your "
                "real frontend origin(s) before going live."
            )
    try:
        yield
    finally:
        await close_queue()
        await run_store.close()
        await daily_budget.close()


app = FastAPI(title="VideoLens AI", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Client-ID", "X-Gemini-Api-Key"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/readiness")
async def readiness() -> dict:
    try:
        redis_ready = await run_store.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Run storage is unavailable.") from exc
    return {
        "status": "ready",
        "mode": "distributed" if settings.queue_enabled else "local",
        "redis": redis_ready,
        "object_storage": settings.object_storage_enabled,
    }


@app.post("/api/runs", response_model=RunCreateResponse, status_code=202)
@limiter.limit(f"{settings.rate_limit_per_hour}/hour")
async def create_run(
    request: Request,
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    accept_terms: bool = Form(default=False),
    principal: Principal = Depends(get_principal),
) -> RunCreateResponse:
    if not accept_terms:
        raise HTTPException(status_code=400, detail="Accept the media-use terms before analysis.")

    # A caller-supplied key spends their own quota, not ours, so it's exempt
    # from the daily budget backstop (which exists purely to bound our own
    # Gemini spend). The per-IP/token rate limit above still applies - it
    # protects server compute (FFmpeg, bandwidth), which BYOK doesn't change.
    gemini_api_key = request.headers.get("x-gemini-api-key", "").strip() or None
    if not gemini_api_key and not await daily_budget.try_consume():
        raise HTTPException(
            status_code=503,
            detail="VideoLens AI has reached its analysis limit for today. Please try again tomorrow.",
        )

    run_id = str(uuid.uuid4())
    source_url = url.strip() if url else None
    if (file is None) == (source_url is None):
        if file is not None:
            await file.close()
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one source: either a media file or a public URL.",
        )

    saved = None
    source_key = None
    try:
        if file is not None:
            saved = await save_upload(run_id, file)
            await enforce_duration_cap(run_id, saved.path)
            if settings.queue_enabled:
                source_key = await upload_source(run_id, saved.path)
                cleanup_run_dir(run_id)

        run = await run_store.create(run_id, principal.subject)
        await enqueue_run(
            run_id,
            saved_path=saved.path if saved and not settings.queue_enabled else None,
            run_dir=saved.run_dir if saved and not settings.queue_enabled else None,
            source_url=source_url,
            source_key=source_key,
            gemini_api_key=gemini_api_key,
        )
        return RunCreateResponse(run_id=run.run_id, status=run.status)
    except MediaValidationError as exc:
        cleanup_run_dir(run_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        cleanup_run_dir(run_id)
        if source_key:
            await delete_source(source_key)
        raise HTTPException(status_code=503, detail="Could not queue the analysis run.") from exc


@app.get("/api/runs", response_model=RunListResponse)
async def list_runs(
    principal: Principal = Depends(get_principal),
) -> RunListResponse:
    runs = await run_store.list_for_owner(principal.subject)
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


@app.get("/api/runs/{run_id}", response_model=RunStatusResponse)
async def get_run(
    run_id: str,
    principal: Principal = Depends(get_principal),
) -> RunStatusResponse:
    run = await run_store.get(run_id)
    if run is None or run.owner_id != principal.subject:
        raise HTTPException(status_code=404, detail="Run not found.")
    return RunStatusResponse(
        run_id=run.run_id,
        status=run.status,
        stage=run.stage,
        result=run.result,
        error=run.error,
    )
