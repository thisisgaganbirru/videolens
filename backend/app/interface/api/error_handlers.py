from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from ...domain.errors import (
    AnalysisUnavailableError,
    ApiKeyNotFoundError,
    AuthenticationError,
    BillingNotConfiguredError,
    DurationLimitError,
    InvalidSourceError,
    MediaValidationError,
    PermissionDeniedError,
    PlanLimitError,
    QuotaExceededError,
    RunNotFoundError,
    RunSchedulingError,
    TermsNotAcceptedError,
    WebhookVerificationError,
    WorkspaceNotFoundError,
)

# Order matters where classes nest: FastAPI matches the most specific
# handler, but keeping the subclass first keeps that fact visible.
_STATUS_BY_ERROR = {
    TermsNotAcceptedError: 400,
    InvalidSourceError: 400,
    DurationLimitError: 400,
    MediaValidationError: 400,
    WebhookVerificationError: 400,
    AuthenticationError: 401,
    PlanLimitError: 402,
    PermissionDeniedError: 403,
    RunNotFoundError: 404,
    WorkspaceNotFoundError: 404,
    ApiKeyNotFoundError: 404,
    AnalysisUnavailableError: 503,
    QuotaExceededError: 503,
    RunSchedulingError: 503,
    BillingNotConfiguredError: 503,
}


def register_error_handlers(app: FastAPI) -> None:
    for error_type, status_code in _STATUS_BY_ERROR.items():

        async def handler(request: Request, exc: Exception, status_code: int = status_code) -> JSONResponse:
            content: dict = {"detail": str(exc)}
            if isinstance(exc, DurationLimitError):
                # Enough for a client to say "upgrade for longer video"
                # without parsing the sentence.
                content["code"] = "duration_limit"
                content["duration_seconds"] = round(exc.duration_seconds, 1)
                content["limit_seconds"] = exc.limit_seconds
            elif isinstance(exc, PlanLimitError):
                content["code"] = "plan_limit"
            return JSONResponse(status_code=status_code, content=content)

        app.add_exception_handler(error_type, handler)
