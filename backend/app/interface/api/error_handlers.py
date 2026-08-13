from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from ...domain.errors import (
    InvalidSourceError,
    MediaValidationError,
    QuotaExceededError,
    RunNotFoundError,
    RunSchedulingError,
    TermsNotAcceptedError,
)

_STATUS_BY_ERROR = {
    TermsNotAcceptedError: 400,
    InvalidSourceError: 400,
    MediaValidationError: 400,
    QuotaExceededError: 503,
    RunSchedulingError: 503,
    RunNotFoundError: 404,
}


def register_error_handlers(app: FastAPI) -> None:
    for error_type, status_code in _STATUS_BY_ERROR.items():

        async def handler(request: Request, exc: Exception, status_code: int = status_code) -> JSONResponse:
            return JSONResponse(status_code=status_code, content={"detail": str(exc)})

        app.add_exception_handler(error_type, handler)
