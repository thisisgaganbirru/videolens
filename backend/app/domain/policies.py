import hashlib
import math
import re
from datetime import datetime, time, timedelta, timezone

CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


def is_valid_client_id(value: str) -> bool:
    return bool(CLIENT_ID_PATTERN.fullmatch(value))


def quota_key_from_headers(authorization: str, client_ip: str) -> str:
    # Keyed by IP, not the client-supplied X-Client-ID: that header is
    # self-reported and free to regenerate, so it carries no quota weight.
    if authorization.startswith("Bearer "):
        digest = hashlib.sha256(authorization.encode()).hexdigest()[:32]
        return f"token:{digest}"
    return f"ip:{client_ip}" if client_ip else "anonymous"


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
