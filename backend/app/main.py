import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request

from .config import settings
from .models import RunCreateResponse, RunStatusResponse
from .pipeline import run_pipeline
from .rate_limit import limiter
from .runs import run_store
from .video import MediaValidationError, enforce_duration_cap, save_upload, validate_media_tools

os.makedirs(settings.temp_dir, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    validate_media_tools()
    sweep_task = asyncio.create_task(run_store.sweep_loop())
    try:
        yield
    finally:
        sweep_task.cancel()


app = FastAPI(title="VideoLens AI", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/runs", response_model=RunCreateResponse, status_code=202)
@limiter.limit(f"{settings.rate_limit_per_hour}/hour")
async def create_run(
    request: Request,
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
) -> RunCreateResponse:
    run_id = str(uuid.uuid4())
    source_url = url.strip() if url else None

    if (file is None) == (source_url is None):
        if file is not None:
            await file.close()
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one source: either a media file or a public URL.",
        )

    try:
        saved = None
        if file is not None:
            saved = await save_upload(run_id, file)
            await enforce_duration_cap(run_id, saved.path)
    except MediaValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run = await run_store.create(run_id)
    asyncio.create_task(
        run_pipeline(
            run_id,
            saved_path=saved.path if saved else None,
            run_dir=saved.run_dir if saved else None,
            source_url=source_url,
        )
    )

    return RunCreateResponse(run_id=run.run_id, status=run.status)


@app.get("/api/runs/{run_id}", response_model=RunStatusResponse)
async def get_run(run_id: str) -> RunStatusResponse:
    run = await run_store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return RunStatusResponse(
        run_id=run.run_id,
        status=run.status,
        stage=run.stage,
        result=run.result,
        error=run.error,
    )
