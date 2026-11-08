"""What a caller is allowed to do, expressed as data the application layer
compares against, never as behaviour.

Auth phase 1 keeps the seam and one plan. `FREE` is today's deployment:
its limits are the operator's `MAX_FILE_SIZE_MB` / `MAX_DURATION_SECONDS`,
passed in rather than read here so the domain never imports `Settings`.
The subscription work re-adds the paid plans and their numbers as rows of
this table; nothing that calls `entitlement_for` has to change shape.
"""

from dataclasses import dataclass
from enum import Enum


class Plan(str, Enum):
    FREE = "free"


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
    raise ValueError(f"No entitlement for plan {plan!r}")
