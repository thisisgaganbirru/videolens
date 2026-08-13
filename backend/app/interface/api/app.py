import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from ...container import container
from ...infrastructure.logging_config import configure_logging
from .error_handlers import register_error_handlers
from .rate_limiter import limiter
from .routes import router

configure_logging()
logger = logging.getLogger(__name__)
os.makedirs(container.settings.temp_dir, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    container.media.validate_tools()
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


app = FastAPI(title="VideoLens AI", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=container.settings.allowed_origin_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Client-ID", "X-Gemini-Api-Key"],
)
register_error_handlers(app)
app.include_router(router)
