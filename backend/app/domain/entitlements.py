"""What each plan is allowed to do, expressed as data the application layer
can compare against, never as behaviour.

The numbers here are the product's pricing table (`docs/product-plan-100k.md`)
and nothing else reads them: a use case asks `entitlement_for(plan)` and
compares, an adapter never looks at a plan name. Keeping the table in the
domain means a price or limit change is one edit and one test, with no
Stripe, Postgres or FastAPI import anywhere near it.
"""

from dataclasses import dataclass, replace
from decimal import ROUND_UP, Decimal
from enum import Enum


class Plan(str, Enum):
    FREE = "free"
    PRO = "pro"
    STUDIO = "studio"
    SCALE = "scale"


class MediaResolution(str, Enum):
    """How many tokens per second of video Gemini spends looking at it.

    Default is ~300 tokens/s, low is ~100 tokens/s. Above a quarter of an hour
    the default resolution costs three times as much and no longer fits the
    model's context for long uploads; low resolution reads on-screen text
    slightly worse but keeps an hour-long video both affordable and possible.
    """

    DEFAULT = "default"
    LOW = "low"


# Above this, video is analyzed at low resolution. Both the margin on paid
# plans and the context window on hour-long media depend on it.
LOW_RESOLUTION_ABOVE_SECONDS = 15 * 60

# Gemini's published per-minute cost at each resolution for the flash model
# family, used only for the `cost_estimate_usd` on usage events - the invoice
# itself comes from Stripe, this is what the margin dashboard reads.
COST_USD_PER_MINUTE = {
    MediaResolution.DEFAULT: Decimal("0.013"),
    MediaResolution.LOW: Decimal("0.005"),
}


@dataclass(frozen=True)
class Entitlement:
    plan: Plan
    minutes_included: int
    max_duration_seconds: int
    max_file_size_mb: int
    seats: int
    # None means a hard cap: the run is refused once the included minutes are
    # gone. A price means the run goes ahead and the extra minutes are billed.
    overage_usd_per_minute: Decimal | None
    api_access: bool
    library: bool

    @property
    def metered(self) -> bool:
        """Whether minutes are counted against this plan at all.

        Anonymous free use is bounded by the shared daily budget instead of a
        per-workspace meter, because there is no workspace to meter.
        """
        return self.plan is not Plan.FREE or self.minutes_included > 0

    def with_max_duration(self, seconds: int | None) -> "Entitlement":
        if seconds is None or seconds <= 0:
            return self
        return replace(self, max_duration_seconds=seconds)


_PLAN_TABLE: dict[Plan, Entitlement] = {
    Plan.FREE: Entitlement(
        plan=Plan.FREE,
        minutes_included=30,
        max_duration_seconds=180,
        max_file_size_mb=200,
        seats=1,
        overage_usd_per_minute=None,
        api_access=False,
        library=False,
    ),
    Plan.PRO: Entitlement(
        plan=Plan.PRO,
        minutes_included=600,
        max_duration_seconds=30 * 60,
        max_file_size_mb=1024,
        seats=1,
        overage_usd_per_minute=Decimal("0.05"),
        api_access=False,
        library=True,
    ),
    Plan.STUDIO: Entitlement(
        plan=Plan.STUDIO,
        minutes_included=3000,
        max_duration_seconds=60 * 60,
        max_file_size_mb=2048,
        seats=3,
        overage_usd_per_minute=Decimal("0.05"),
        api_access=True,
        library=True,
    ),
    Plan.SCALE: Entitlement(
        plan=Plan.SCALE,
        minutes_included=12000,
        max_duration_seconds=120 * 60,
        max_file_size_mb=2048,
        seats=10,
        overage_usd_per_minute=Decimal("0.04"),
        api_access=True,
        library=True,
    ),
}


def entitlement_for(plan: Plan | str) -> Entitlement:
    return _PLAN_TABLE[Plan(plan)]


def billable_minutes(duration_seconds: float) -> Decimal:
    """Minutes of media, rounded up to the next hundredth.

    Rounding up (never to nearest) so a 6-second clip is never free, and to
    two places so a 200-run month does not drift from what Stripe's meter
    sums. Negative or zero durations bill as zero rather than raising: they
    only occur when probing failed, and the run has already failed by then.
    """
    if duration_seconds <= 0:
        return Decimal("0")
    return (Decimal(str(duration_seconds)) / Decimal(60)).quantize(Decimal("0.01"), rounding=ROUND_UP)


def media_resolution_for(duration_seconds: float | None) -> MediaResolution:
    if duration_seconds is not None and duration_seconds > LOW_RESOLUTION_ABOVE_SECONDS:
        return MediaResolution.LOW
    return MediaResolution.DEFAULT


def estimate_cost_usd(duration_seconds: float, resolution: MediaResolution) -> Decimal:
    return (billable_minutes(duration_seconds) * COST_USD_PER_MINUTE[resolution]).quantize(Decimal("0.0001"))


def can_start_run(entitlement: Entitlement, minutes_used: Decimal | float) -> bool:
    """Whether a workspace may start another run given what it has used.

    Checked before the media is fetched, so the duration is not known yet;
    the comparison is against the allowance as a whole rather than against
    what this run would add. A plan with an overage price is never blocked
    here - its extra minutes are billed, not refused.
    """
    if entitlement.overage_usd_per_minute is not None:
        return True
    return Decimal(str(minutes_used)) < Decimal(entitlement.minutes_included)
