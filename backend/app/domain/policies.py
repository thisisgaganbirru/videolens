import hashlib
import math
import re
from datetime import datetime, time, timedelta, timezone

from .entities import AuthMethod, Principal

CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


def is_valid_client_id(value: str) -> bool:
    return bool(CLIENT_ID_PATTERN.fullmatch(value))


# Every VideoLens API key starts with this. It is what lets a bearer header be
# routed to the key lookup without a database read: an identity-provider JWT
# starts with "eyJ" (base64 of `{"`), never with this.
API_KEY_PREFIX = "vl_live_"


# The `role` claim on a Supabase access token for a real signed-in user
# (anonymous sign-ins are `authenticated` too, but flagged `is_anonymous`).
SIGNED_IN_ROLE = "authenticated"


def bearer_credential(authorization: str) -> str:
    """The credential in an `Authorization: Bearer <credential>` header, or
    "" for any other scheme or an empty credential. The scheme name is
    case-insensitive (RFC 9110 section 11.1), so `bearer x` counts."""
    scheme, _, credential = authorization.strip().partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return credential.strip()


def looks_like_api_key(value: str) -> bool:
    return value.startswith(API_KEY_PREFIX)


def can_access_run(principal: Principal, run) -> bool:
    """The one ownership rule: a run is visible to the owner it was created
    for and to nobody else. `run` is anything with an `owner_id`."""
    return run is not None and run.owner_id == principal.owner_id


def quota_key(principal: Principal, client_ip: str) -> str:
    """Which rate-limit bucket a resolved caller spends from.

    A signed-in person is keyed by account, not by token: the token rotates
    every time the client refreshes it (hourly with supabase-js), and keying
    on its hash reset the hourly window with it. An API key spends from the
    account that owns its workspace, so ten keys are one quota, not ten.
    Anonymous callers stay keyed by IP, never by the self-reported
    X-Client-ID, which is free to regenerate.
    """
    if principal.method in (AuthMethod.TOKEN, AuthMethod.API_KEY):
        if principal.account_id:
            return f"account:{principal.account_id}"
        # No account directory (DATABASE_URL blank in a deployed API): the
        # subject is still stable across token refreshes, unlike the token.
        return principal.subject
    return f"ip:{client_ip}" if client_ip else "anonymous"


def quota_key_from_headers(authorization: str, client_ip: str) -> str:
    """Fallback bucket for a request whose caller was not resolved (a route
    without `get_principal`, or resolution failing). Keyed by IP, not the
    client-supplied X-Client-ID: that header is self-reported and free to
    regenerate, so it carries no quota weight."""
    credential = bearer_credential(authorization)
    if credential:
        digest = hashlib.sha256(credential.encode()).hexdigest()[:32]
        return f"token:{digest}"
    return f"ip:{client_ip}" if client_ip else "anonymous"


def client_ip_from_forwarded(forwarded: str, peer: str, trusted_hops: int) -> str:
    """The caller's IP, given the X-Forwarded-For header and the socket peer.

    Each proxy a request passes through appends the address it received the
    request from, so the *rightmost* entries are the ones written by proxies
    we control and the leftmost is whatever the client sent - which it is free
    to make up. `trusted_hops` is how many trailing entries the deployment's
    own proxies add, counting the client entry they write; the client is the
    entry that many from the end. On Railway it is 2: the edge rewrites the
    header to `<client>, <edge hop>` and the edge hop changes from request to
    request, so the last entry is never the client. A header with fewer entries than that
    did not pass through the expected proxies, and its first entry is used
    rather than trusting nothing (the peer, behind a proxy, is the proxy).
    `trusted_hops <= 0` ignores the header entirely and uses the peer, for a
    service that is reached directly.
    """
    if trusted_hops <= 0:
        return peer
    entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
    if not entries:
        return peer
    if len(entries) >= trusted_hops:
        return entries[-trusted_hops]
    return entries[0]


def is_run_stale(status, updated_at: datetime, timeout_seconds: int) -> bool:
    """True when a run claims to be in progress but has stopped reporting.

    A process can die between marking a run PROCESSING and marking it done -
    an OOM kill, a container replacement, a garbage-collected task. Nothing is
    left to fail the run, so without this it would spin in the UI until its
    storage TTL expired, which is days. Anything that has not touched the run
    in longer than a whole job could legitimately take is treated as dead.
    """
    if status not in {"queued", "processing"}:
        return False
    reference = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - reference).total_seconds() > timeout_seconds


def seconds_until_next_utc_day(now: datetime) -> int:
    """Whole seconds from `now` until the next UTC midnight, never below 1.

    The daily budget and the free-run allowance both reset there, so this is
    the honest `Retry-After` for either. Rounded up: a client told "0" would
    retry straight into the same refusal.
    """
    current = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    midnight = datetime.combine(current.date() + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return max(1, math.ceil((midnight - current).total_seconds()))


def seconds_until(reset_at_epoch: float, now_epoch: float) -> int:
    """Whole seconds from `now_epoch` until `reset_at_epoch`, never below 1
    (rounded up, for the same reason as above)."""
    return max(1, math.ceil(reset_at_epoch - now_epoch))


def _as_utc(now: datetime) -> datetime:
    return now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)


def utc_month(now: datetime) -> str:
    """The UTC calendar month `now` falls in, as "YYYY-MM": the period the
    account free-run allowance counts against."""
    return f"{_as_utc(now):%Y-%m}"


def start_of_next_utc_month(now: datetime) -> datetime:
    """00:00 UTC on the first day of the month after `now`'s: when an
    account's monthly free runs reset."""
    current = _as_utc(now)
    year, month = (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
    return datetime(year, month, 1, tzinfo=timezone.utc)


# ------------------------------------------------------------------ billing

# Stripe subscription statuses that grant the paid plan. `past_due`,
# `unpaid`, `canceled`, `incomplete`, `incomplete_expired` and `paused` do
# not: the account is on the free plan until Stripe reports it paid again.
PAID_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing"})

# Statuses of a subscription that still exists in Stripe and may bill again.
# A new checkout is refused while one of these is held (no second
# subscription), and account deletion cancels it first.
LIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing", "past_due", "unpaid", "incomplete", "paused"})

# How long past `current_period_end` a subscription still reads as paid
# without a webhook saying it renewed. Covers Stripe's renewal and retry
# timing; stops a missed `customer.subscription.deleted` from leaving an
# account paid for ever.
SUBSCRIPTION_RENEWAL_GRACE = timedelta(days=3)


def subscription_grants_paid(status: str | None, current_period_end: datetime | None, now: datetime) -> bool:
    if status not in PAID_SUBSCRIPTION_STATUSES:
        return False
    if current_period_end is None:
        return True
    return now <= current_period_end + SUBSCRIPTION_RENEWAL_GRACE


def subscription_is_live(status: str | None) -> bool:
    return status in LIVE_SUBSCRIPTION_STATUSES
