"""The one place a media adapter turns "no limits passed" into limits.

Every enforcement point takes the run's `MediaLimits` (chosen per caller by
`application/entitlements.py`). None means the standard deployment limits,
which is what a caller that predates per-caller limits (an old queued job, a
direct adapter call in a test) always got.
"""

from ...domain.entitlements import MediaLimits, MediaTier
from ..config import Settings


def effective_limits(settings: Settings, limits: MediaLimits | None) -> MediaLimits:
    if limits is not None:
        return limits
    return MediaLimits(
        tier=MediaTier.STANDARD,
        max_duration_seconds=settings.max_duration_seconds,
        max_file_size_mb=settings.max_file_size_mb,
    )
