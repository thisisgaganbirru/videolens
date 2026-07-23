import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request

from .config import settings
from .jobs import job_store
from .models import JobCreateResponse, JobStatusResponse
from .pipeline import run_job
from .rate_limit import limiter
from .video import VideoValidationError, enforce_duration_cap, save_upload

os.makedirs(settings.temp_dir, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    sweep_task = asyncio.create_task(job_store.sweep_loop())
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


@app.post("/api/jobs", response_model=JobCreateResponse, status_code=202)
@limiter.limit(f"{settings.rate_limit_per_hour}/hour")
async def create_job(request: Request, file: UploadFile = File(...)) -> JobCreateResponse:
    job_id = str(uuid.uuid4())

    try:
        saved = await save_upload(job_id, file)
        await enforce_duration_cap(job_id, saved.path)
    except VideoValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = await job_store.create(job_id)
    asyncio.create_task(run_job(job_id, saved.path, saved.job_dir))

    return JobCreateResponse(job_id=job.job_id, status=job.status)


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    job = await job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        result=job.result,
        error=job.error,
    )
