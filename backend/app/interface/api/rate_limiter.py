import logging
import time

from slowapi import Limiter
from starlette.requests import Request

from ...domain.entities import Principal
from ...domain.policies import client_ip_from_forwarded, quota_key_from_headers, seconds_until
from ...domain.policies import quota_key as principal_quota_key
from ...infrastructure.config import settings

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    # Railway's edge writes X-Forwarded-For as "<client>, <edge hop>". Only
    # the entries the deployment's own proxies wrote are trusted
    # (TRUSTED_PROXY_HOPS, counted from the right, 2 on Railway); the leftmost
    # entry can be client-supplied and used to be what this read, which let a
    # forged header pick a fresh rate-limit bucket per request. Falls back to
    # the socket peer for local/direct runs.
    peer = request.client.host if request.client else ""
    return client_ip_from_forwarded(
        request.headers.get("x-forwarded-for", ""), peer, settings.trusted_proxy_hops
    )


def quota_key(request: Request) -> str:
    """The rate-limit bucket for this request.

    Keyed on the caller `get_principal` resolved (it leaves it on
    `request.state`; slowapi's route decorator runs the check inside the
    endpoint, after dependencies): `account:<id>` for a signed-in person or an
    API key, `ip:<ip>` for anonymous callers (`policies.quota_key`). A route
    without `get_principal`, or anything going wrong here, falls back to the
    header-based key (token hash, else IP) the limiter used before accounts
    existed; a request with a bad credential is refused with a 401 by the
    dependency before it ever reaches the limit check.
    """
    ip = client_ip(request)
    try:
        principal = getattr(request.state, "principal", None)
        if isinstance(principal, Principal):
            return principal_quota_key(principal, ip)
    except Exception:  # noqa: BLE001 - never fail a request over its bucket name
        logger.warning("Could not derive the quota key from the principal", exc_info=True)
    return quota_key_from_headers(request.headers.get("authorization", ""), ip)


# Redis-backed so the limit holds across worker processes/replicas, not just
# in one process's memory. Falls back to in-memory storage when no Redis is
# configured (single-process local/dev runs).
#
# key_style="endpoint": one bucket per route function, not per URL. slowapi's
# default ("url") buckets by request path, so GET /api/runs/{run_id} got a
# fresh bucket for every run id and READ_RATE_LIMIT_PER_MINUTE never tripped
# for a caller cycling ids (measured on Railway, 2026-11-07).
limiter = Limiter(
    key_func=quota_key,
    storage_uri=settings.redis_url or "memory://",
    default_limits=[],
    key_style="endpoint",
)



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
