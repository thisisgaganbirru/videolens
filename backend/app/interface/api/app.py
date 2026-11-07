import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request

from ...container import container
from ...domain.errors import RateLimitedError
from ...infrastructure.logging_config import configure_logging
from .error_handlers import register_error_handlers, retry_after_headers
from .rate_limiter import limiter, retry_after_seconds
from .routes import router
from .security_headers import SecurityHeadersMiddleware

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    container.media.validate_tools()
    # Creates the directory too, so this replaces the bare `os.makedirs` that
    # used to run at import. That call is what made a bad TEMP_DIR invisible:
    # it succeeded on any string Linux accepts as a directory name.
    container.media.validate_temp_dir()
    settings = container.settings
    container.device_tokens.validate_configuration()
    if settings.queue_enabled:
        await container.run_repository.ping()
        if not container.object_store.enabled:
            raise RuntimeError("S3-compatible object storage is required when Redis queueing is enabled.")
        origin_error = settings.distributed_origin_error()
        if origin_error:
            # Refused, not warned: a deployed API with a CORS wildcard is open
            # to every website, and a warning in a platform log reaches nobody.
            raise RuntimeError(origin_error)
    try:
        yield
    finally:
        await container.close()


async def _rate_limited(request: Request, exc: Exception) -> JSONResponse:
    """slowapi's stock handler answers `{"error": ...}`, but every other error
    in this API answers `{"detail": ...}` and that is the key the frontend
    reads - so a rate-limited caller used to be shown the bare fallback
    "Could not create run (429)" instead of anything about rate limiting.

    Translated into the domain's RateLimitedError so the 429 is built the same
    way as every other error, `Retry-After` included (seconds until the
    limiter's window frees; the frontend words the wait from it)."""
    error = RateLimitedError(
        "You're going a bit fast. Wait a minute and try again.",
        retry_after_seconds=retry_after_seconds(request),
    )
    return JSONResponse(status_code=429, content={"detail": str(error)}, headers=retry_after_headers(error))


app = FastAPI(title="VideoLens AI", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limited)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=container.settings.allowed_origin_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Client-ID", "X-Gemini-Api-Key", "X-Device-Token"],
    # Not a CORS-safelisted response header: without this a cross-origin
    # fetch (the web app and the Android WebView both are) reads it as null.
    expose_headers=["Retry-After"],
)
# Outermost (added last), so preflights, rate-limit refusals and error
# responses carry the headers too.
app.add_middleware(SecurityHeadersMiddleware)
register_error_handlers(app)
app.include_router(router)
