from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from starlette.requests import Request

from ...container import container
from ...domain.entities import CapabilityReport, Principal, ReleaseIndex
from .dependencies import get_principal
from .rate_limiter import limiter
from .schemas import RunCreateResponse, RunListResponse, RunStatusResponse, RunSummary

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
