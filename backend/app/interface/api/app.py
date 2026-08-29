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
from ...infrastructure.logging_config import configure_logging
from .error_handlers import register_error_handlers
from .rate_limiter import limiter
from .routes import router

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
    if settings.queue_enabled:
        await container.run_repository.ping()
        if not container.object_store.enabled:
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
        await container.close()


async def _rate_limited(request: Request, exc: Exception) -> JSONResponse:
    """slowapi's stock handler answers `{"error": ...}`, but every other error
    in this API answers `{"detail": ...}` and that is the key the frontend
    reads - so a rate-limited caller used to be shown the bare fallback
    "Could not create run (429)" instead of anything about rate limiting."""
    return JSONResponse(
        status_code=429,
        content={"detail": "You're going a bit fast. Wait a minute and try again."},
    )


app = FastAPI(title="VideoLens AI", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limited)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=container.settings.allowed_origin_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Client-ID", "X-Gemini-Api-Key"],
)
register_error_handlers(app)
app.include_router(router)
