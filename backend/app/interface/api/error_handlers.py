import logging
from datetime import timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from ...domain.errors import (
    AccountDeletionError,
    AccountPendingDeletionError,
    AccountRestoreClosedError,
    InvalidCursorError,
    SavedRunNotFoundError,
    ApiKeyLimitError,
    ApiKeyNotFoundError,
    AuthenticationError,
    AuthNotConfiguredError,
    AlreadySubscribedError,
    BillingError,
    BillingIntervalError,
    BillingNotConfiguredError,
    BillingProviderError,
    ComplimentaryPlanError,
    ExtraRunsCapReachedError,
    NoBillingAccountError,
    SubscriptionCancelFailedError,
    WebhookSignatureError,
    ClientIdInvalidError,
    DeviceTokenInvalidError,
    ForbiddenError,
    FreeRunsExhaustedError,
    AnalysisUnavailableError,
    InvalidSourceError,
    LongRunInProgressError,
    MediaValidationError,
    QuotaExceededError,
    RateLimitedError,
    RunNotFoundError,
    RunSchedulingError,
    TermsNotAcceptedError,
)

logger = logging.getLogger("videolens")

# Billing errors all answer {"detail", "code"}: the client acts on the code
# (open the portal instead of checkout, hide the upgrade button, ...).
_BILLING_STATUS = {
    BillingNotConfiguredError: 503,
    AlreadySubscribedError: 409,
    ComplimentaryPlanError: 409,
    NoBillingAccountError: 404,
    BillingIntervalError: 400,
    BillingProviderError: 503,
}

_STATUS_BY_ERROR = {
    TermsNotAcceptedError: 400,
    InvalidSourceError: 400,
    MediaValidationError: 400,
    AnalysisUnavailableError: 503,
    QuotaExceededError: 503,
    RunSchedulingError: 503,
    RunNotFoundError: 404,
    SavedRunNotFoundError: 404,
    InvalidCursorError: 400,
    RateLimitedError: 429,
    ClientIdInvalidError: 400,
    ForbiddenError: 403,
    ApiKeyNotFoundError: 404,
    ApiKeyLimitError: 409,
    AccountDeletionError: 500,
    # Covers AccountsNotConfiguredError, its subclass.
    AuthNotConfiguredError: 503,
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
            content={
                "detail": str(exc),
                "code": "free_runs_used",
                "scope": exc.scope,
                "period": exc.period,
                "limit": exc.limit,
                "used": exc.used,
            },
        )

    # 401 with the challenge header RFC 9110 asks for; the message never
    # echoes the credential.
    async def unauthenticated(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=401, content={"detail": str(exc)}, headers={"WWW-Authenticate": "Bearer"}
        )

    # 429 with a `code`, so the client can tell it from the per-IP rate limit
    # (which has none) and say "wait for the long one" rather than "slow down".
    async def long_run_in_progress(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc), "code": "long_run_in_progress"})

    async def billing_error(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, BillingError)
        status_code = next((code for kind, code in _BILLING_STATUS.items() if isinstance(exc, kind)), 503)
        return JSONResponse(status_code=status_code, content={"detail": str(exc), "code": exc.code})

    async def webhook_signature(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": "Invalid signature.", "code": "invalid_signature"})

    # 402 like free_runs_used, with its own code: a paid account at the
    # monthly safety cap on extra runs, not a free account out of runs.
    async def extra_runs_cap(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, ExtraRunsCapReachedError)
        return JSONResponse(
            status_code=402, content={"detail": str(exc), "code": "extra_runs_cap", "limit": exc.limit}
        )

    # Registered on the subclass, so it wins over AccountDeletionError's 500:
    # nothing was deleted, and retrying is the right move.
    async def subscription_cancel_failed(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, SubscriptionCancelFailedError)
        logger.warning("Account deletion refused: subscription not cancelled (%s)", exc.log_detail)
        return JSONResponse(status_code=503, content={"detail": str(exc), "code": "subscription_cancel_failed"})

    # 410 with a `code` and the date: the client shows "Restore your
    # account?" and how long it has left (docs/backend/saved-history.md).
    async def account_pending_deletion(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AccountPendingDeletionError)
        # The same UTC "Z" form pydantic gives `DELETE /api/me`'s purge_at.
        purge_at = (
            exc.purge_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if exc.purge_at is not None
            else None
        )
        return JSONResponse(
            status_code=410,
            content={"detail": str(exc), "code": "account_pending_deletion", "purge_at": purge_at},
        )

    async def restore_closed(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=410, content={"detail": str(exc), "code": "restore_window_closed"})

    app.add_exception_handler(AccountPendingDeletionError, account_pending_deletion)
    app.add_exception_handler(AccountRestoreClosedError, restore_closed)
    app.add_exception_handler(BillingError, billing_error)
    app.add_exception_handler(WebhookSignatureError, webhook_signature)
    app.add_exception_handler(ExtraRunsCapReachedError, extra_runs_cap)
    app.add_exception_handler(SubscriptionCancelFailedError, subscription_cancel_failed)
    app.add_exception_handler(AuthenticationError, unauthenticated)
    app.add_exception_handler(LongRunInProgressError, long_run_in_progress)
    app.add_exception_handler(DeviceTokenInvalidError, device_token_invalid)
    app.add_exception_handler(FreeRunsExhaustedError, free_runs_used)
