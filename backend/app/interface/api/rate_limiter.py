from slowapi import Limiter
from starlette.requests import Request

from ...domain.policies import quota_key_from_headers
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
