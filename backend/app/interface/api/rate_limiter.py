import json
import logging
import time

from slowapi import Limiter
from starlette.requests import Request

from ...domain.policies import client_ip_from_forwarded, quota_key_from_headers, seconds_until
from ...infrastructure.config import settings


def client_ip(request: Request) -> str:
    # Deployment targets (Railway/Render) front the app with a proxy that
    # appends the caller to X-Forwarded-For. Only the entries the deployment's
    # own proxies wrote are trusted (TRUSTED_PROXY_HOPS, counted from the
    # right); the leftmost entry is client-supplied and used to be what this
    # read, which let a forged header pick a fresh rate-limit bucket per
    # request. Falls back to the socket peer for local/direct runs.
    peer = request.client.host if request.client else ""
    return client_ip_from_forwarded(
        request.headers.get("x-forwarded-for", ""), peer, settings.trusted_proxy_hops
    )


def quota_key(request: Request) -> str:
    return quota_key_from_headers(request.headers.get("authorization", ""), client_ip(request))


# Redis-backed so the limit holds across worker processes/replicas, not just
# in one process's memory. Falls back to in-memory storage when no Redis is
# configured (single-process local/dev runs).
limiter = Limiter(key_func=quota_key, storage_uri=settings.redis_url or "memory://", default_limits=[])


logger = logging.getLogger(__name__)


# TEMPORARY diagnostic, removed in the fix PR
PROBE_MARKER = "client-ip-probe"


def log_client_ip_probe(request: Request) -> None:
    # TEMPORARY diagnostic, removed in the fix PR. Logs the raw proxy headers
    # and the IP the limiter keys on, only for a request that opts in with
    # `X-VideoLens-Probe: 1`, so ordinary callers' IPs never reach the logs.
    if request.headers.get("x-videolens-probe", "") != "1":
        return
    headers = request.headers
    logger.info(
        "%s %s",
        PROBE_MARKER,
        json.dumps(
            {
                "x_forwarded_for": headers.get("x-forwarded-for"),
                "x_real_ip": headers.get("x-real-ip"),
                "forwarded": headers.get("forwarded"),
                "x_envoy_external_address": headers.get("x-envoy-external-address"),
                "peer": request.client.host if request.client else None,
                "resolved": client_ip(request),
                "trusted_proxy_hops": settings.trusted_proxy_hops,
                "limiter_storage": type(limiter._storage).__name__,
            }
        ),
    )


class ClientIpProbeMiddleware:  # TEMPORARY diagnostic, removed in the fix PR
    """Pure ASGI (BaseHTTPMiddleware buffers streaming bodies)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            try:
                log_client_ip_probe(Request(scope))
            except Exception:  # noqa: BLE001 - a diagnostic must never fail a request
                logger.warning("client-ip probe failed", exc_info=True)
        await self.app(scope, receive, send)


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
