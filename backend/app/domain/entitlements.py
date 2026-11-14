"""What a caller is allowed to do, expressed as data the application layer
compares against, never as behaviour.

Auth phase 1 keeps the seam and one plan. `FREE` is today's deployment:
its limits are the operator's `MAX_FILE_SIZE_MB` / `MAX_DURATION_SECONDS`,
passed in rather than read here so the domain never imports `Settings`.
The subscription work re-adds the paid plans and their numbers as rows of
this table; nothing that calls `entitlement_for` has to change shape.
"""

from dataclasses import dataclass
from typing import Optional
from enum import Enum


class Plan(str, Enum):
    FREE = "free"
    # The one paid plan (docs/backend/billing.md): an active or trialing
    # Stripe subscription. Its numbers come from settings, like FREE's.
    PAID = "paid"


@dataclass(frozen=True)
class Entitlement:
    plan: Plan
    max_duration_seconds: int
    max_file_size_mb: int
    # Whether minutes are counted against a per-workspace allowance. Nothing
    # is metered in this phase: free use is bounded by the shared daily
    # budget and the free-run allowance instead.
    metered: bool
    # Agents are a first-class client, so API keys are open to every signed-in
    # person in this phase (the old branch gated them on a paid plan).
    api_access: bool
    library: bool


def entitlement_for(plan: Plan | str, *, max_duration_seconds: int, max_file_size_mb: int) -> Entitlement:
    plan = Plan(plan)
    # One plan today; the match keeps an unknown value a loud error rather
    # than a silent free tier once more members exist.
    if plan is Plan.FREE:
        return Entitlement(
            plan=Plan.FREE,
            max_duration_seconds=max_duration_seconds,
            max_file_size_mb=max_file_size_mb,
            metered=False,
            api_access=True,
            library=False,
        )
    if plan is Plan.PAID:
        return Entitlement(
            plan=Plan.PAID,
            max_duration_seconds=max_duration_seconds,
            max_file_size_mb=max_file_size_mb,
            # Runs past the included ones are billed per run.
            metered=True,
            api_access=True,
            library=False,
        )
    raise ValueError(f"No entitlement for plan {plan!r}")


# --------------------------------------------------------------- media limits
#
# How long and how large one run's media may be. Separate from `Entitlement`
# (the plan) because it depends on the *request*, not only the caller: the
# bigger set needs a signed-in caller AND their own Gemini key on this run,
# and the key is never stored server-side, so no plan lookup can know it.


class MediaTier(str, Enum):
    STANDARD = "standard"
    # Signed in (JWT or account API key) and bringing their own Gemini key.
    SIGNED_IN_BYOK = "signed_in_byok"
    # An account on the paid plan, with or without its own key. Same numbers
    # as SIGNED_IN_BYOK by default (PAID_MAX_*).
    PAID = "paid"

    @property
    def long_job(self) -> bool:
        """Runs under the longer worker timeout and stale threshold, and may
        hold the one-long-run-per-account slot."""
        return self in (MediaTier.SIGNED_IN_BYOK, MediaTier.PAID)


@dataclass(frozen=True)
class MediaLimits:
    """The limits one run was admitted under. Travels with the run to the
    worker (`to_job_arg`), so the worker enforces exactly what the API
    admitted instead of re-deriving it from a key it no longer has.

    `upgrade_action` / `upgrade_*` describe the bigger set this caller would
    reach by signing in and/or adding a key ("Sign in for videos up to
    10:00."), or are None when there is nothing bigger to reach.
    `long_run_key` is the account (or subject) a run above the standard
    limits holds its one long-run slot under; set only on the bigger tier.
    """

    tier: MediaTier
    max_duration_seconds: int
    max_file_size_mb: int
    upgrade_action: Optional[str] = None
    upgrade_max_duration_seconds: Optional[int] = None
    upgrade_max_file_size_mb: Optional[int] = None
    long_run_key: Optional[str] = None

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    def to_job_arg(self) -> dict:
        """Plain primitives for the arq job (pickled across deploys, so no
        class identity in it). Holds no credential: never the BYOK key."""
        return {
            "tier": self.tier.value,
            "max_duration_seconds": self.max_duration_seconds,
            "max_file_size_mb": self.max_file_size_mb,
            "upgrade_action": self.upgrade_action,
            "upgrade_max_duration_seconds": self.upgrade_max_duration_seconds,
            "upgrade_max_file_size_mb": self.upgrade_max_file_size_mb,
            "long_run_key": self.long_run_key,
        }

    @classmethod
    def from_job_arg(cls, value: Optional[dict]) -> Optional["MediaLimits"]:
        """None for a job enqueued before limits travelled with it: the
        worker then applies the standard limits, as it always did."""
        if not value:
            return None
        return cls(
            tier=MediaTier(value.get("tier", MediaTier.STANDARD.value)),
            max_duration_seconds=int(value["max_duration_seconds"]),
            max_file_size_mb=int(value["max_file_size_mb"]),
            upgrade_action=value.get("upgrade_action"),
            upgrade_max_duration_seconds=value.get("upgrade_max_duration_seconds"),
            upgrade_max_file_size_mb=value.get("upgrade_max_file_size_mb"),
            long_run_key=value.get("long_run_key"),
        )


def clock(seconds: float) -> str:
    """`m:ss`, matching how the frontend prints every other timestamp."""
    total = max(0, round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def duration_over_limit_message(duration_seconds: float, limits: MediaLimits) -> str:
    message = f"This video is {clock(duration_seconds)} long. The limit is {clock(limits.max_duration_seconds)}."
    reach = limits.upgrade_max_duration_seconds
    # Only offered when it would actually have fit: telling someone with a
    # 40-minute video to sign in for 10 minutes is a dead end.
    if limits.upgrade_action and reach and duration_seconds <= reach:
        message += f" {limits.upgrade_action} for videos up to {clock(reach)}."
    return message


def size_over_limit_message(limits: MediaLimits, *, subject: str = "That file") -> str:
    message = f"{subject} is over the {limits.max_file_size_mb}MB limit."
    # The total is usually unknown here (reading stops at the cap), so the
    # hint is offered whenever a bigger set exists.
    if limits.upgrade_action and limits.upgrade_max_file_size_mb:
        message += f" {limits.upgrade_action} for files up to {limits.upgrade_max_file_size_mb}MB."
    return message
