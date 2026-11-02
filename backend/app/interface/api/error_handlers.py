from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from ...domain.errors import (
    DeviceTokenInvalidError,
    FreeRunsExhaustedError,
    AnalysisUnavailableError,
    InvalidSourceError,
    MediaValidationError,
    QuotaExceededError,
    RateLimitedError,
    RunNotFoundError,
    RunSchedulingError,
    TermsNotAcceptedError,
)

_STATUS_BY_ERROR = {
    TermsNotAcceptedError: 400,
    InvalidSourceError: 400,
    MediaValidationError: 400,
    AnalysisUnavailableError: 503,
    QuotaExceededError: 503,
    RunSchedulingError: 503,
    RunNotFoundError: 404,
    RateLimitedError: 429,
}


def retry_after_headers(exc: Exception) -> dict[str, str] | None:
    """`Retry-After` (delta-seconds) for an error that knows when to retry.

    Domain errors carry `retry_after_seconds`; only this layer knows it is an
    HTTP header. The frontend reads it on a 429 ("Try again in about N
    minutes"), and it is listed in the CORS `expose_headers` in app.py, or a
    cross-origin `fetch` could not see it at all."""
    seconds = getattr(exc, "retry_after_seconds", None)
    if not isinstance(seconds, int) or seconds <= 0:
        return None
    return {"Retry-After": str(seconds)}


def register_error_handlers(app: FastAPI) -> None:
    for error_type, status_code in _STATUS_BY_ERROR.items():

        async def handler(request: Request, exc: Exception, status_code: int = status_code) -> JSONResponse:
            return JSONResponse(
                status_code=status_code, content={"detail": str(exc)}, headers=retry_after_headers(exc)
            )

        app.add_exception_handler(error_type, handler)

    # These two carry a machine-readable `code` (plus the device's numbers
    # for 402) on top of the usual `detail`, because the client acts on them:
    # refetch a device token and retry once, or show the "add your key" state.
    async def device_token_invalid(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(exc), "code": "device_token_invalid"})

    async def free_runs_used(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, FreeRunsExhaustedError)
        return JSONResponse(
            status_code=402,
            content={"detail": str(exc), "code": "free_runs_used", "limit": exc.limit, "used": exc.used},
        )

    app.add_exception_handler(DeviceTokenInvalidError, device_token_invalid)
    app.add_exception_handler(FreeRunsExhaustedError, free_runs_used)
