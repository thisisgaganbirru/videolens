import logging
import time

from slowapi import Limiter
from starlette.requests import Request

from ...domain.policies import quota_key_from_headers, seconds_until
from ...infrastructure.config import settings


def client_ip(request: Request) -> str:
    # Deployment targets (Railway/Render) front the app with a proxy that
    # sets X-Forwarded-For; fall back to the socket peer for local/direct runs.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def quota_key(request: Request) -> str:
    return quota_key_from_headers(request.headers.get("authorization", ""), client_ip(request))


# Redis-backed so the limit holds across worker processes/replicas, not just
# in one process's memory. Falls back to in-memory storage when no Redis is
# configured (single-process local/dev runs).
limiter = Limiter(key_func=quota_key, storage_uri=settings.redis_url or "memory://", default_limits=[])


logger = logging.getLogger(__name__)


def retry_after_seconds(request: Request, rate_limiter: Limiter = limiter) -> int | None:
    """Seconds until the limit the request just hit frees a slot, or None.

    slowapi records the tripped limit on `request.state.view_rate_limit` as
    (RateLimitItem, key args); the storage's window stats give the window's
    reset time (fixed window, slowapi's default strategy). Only used to word
    the 429, so any failure here (Redis blip, no recorded limit) degrades to
    no header rather than to a 500.
    """
    current = getattr(request.state, "view_rate_limit", None)
    if not current:
        return None
    try:
        item, args = current
        reset_at, _remaining = rate_limiter.limiter.get_window_stats(item, *args)
        return seconds_until(reset_at, time.time())
    except Exception:  # noqa: BLE001 - header is a courtesy, never fail the 429 over it
        logger.warning("Could not read the rate-limit window for Retry-After", exc_info=True)
        return None
