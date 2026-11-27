"""Pre-flight estimate of a run's video input tokens, and the budget rule
that keeps GEMINI_VIDEO_FPS / GEMINI_MEDIA_RESOLUTION from running away.

SDK-free on purpose (like `source_context.py`), so it is tested as plain
arithmetic. Numbers are Google's Gemini 3 media-resolution table (read
2026-11-26): 70 tokens a video frame at the default, `low` and `medium`
(Gemini 3 treats `medium` exactly like `low` for video), 280 at `high`;
audio is 25 tokens a second at every level. An estimate, not a count: the
real figures are in the engine's "Gemini usage" log line.
"""

import math
from dataclasses import dataclass
from typing import Optional

# Gemini's own sampling rate when GEMINI_VIDEO_FPS is unset (0).
DEFAULT_FPS = 1.0
TOKENS_PER_FRAME_DEFAULT = 70
TOKENS_PER_FRAME_HIGH = 280
AUDIO_TOKENS_PER_SECOND = 25


def tokens_per_frame(resolution: str) -> int:
    """Blank (the model's default), "low" and "medium" are 70; "high" 280."""
    return TOKENS_PER_FRAME_HIGH if resolution == "high" else TOKENS_PER_FRAME_DEFAULT


def estimate_video_tokens(video_seconds: float, fps: float, resolution: str) -> int:
    """seconds x (tokens a frame x fps + 25 audio tokens a second), rounded
    up. `fps` 0 means Gemini's default of 1. Linear in seconds, so a
    carousel's video slides are estimated from their total length."""
    effective_fps = fps if fps > 0 else DEFAULT_FPS
    per_second = tokens_per_frame(resolution) * effective_fps + AUDIO_TOKENS_PER_SECOND
    return math.ceil(max(video_seconds, 0.0) * per_second)


@dataclass(frozen=True)
class SamplingDecision:
    """The fps and resolution a run is actually sent with. `estimate` is the
    configured settings' estimate (None when it could not be made), and
    `downgraded` is True when the budget sent the run back to defaults."""

    fps: float
    resolution: str
    estimate: Optional[int]
    downgraded: bool = False


def within_budget(
    video_seconds: Optional[float], fps: float, resolution: str, budget: int
) -> SamplingDecision:
    """The configured `fps` / `resolution`, or Gemini's defaults (0, "")
    when their estimate is above `budget`. Unchanged when the budget is off
    (<= 0), the length is unknown, or both settings are already defaults: a
    run with the settings unset is never touched."""
    if video_seconds is None:
        return SamplingDecision(fps, resolution, None)
    estimate = estimate_video_tokens(video_seconds, fps, resolution)
    if budget <= 0 or (fps <= 0 and not resolution) or estimate <= budget:
        return SamplingDecision(fps, resolution, estimate)
    return SamplingDecision(0.0, "", estimate, downgraded=True)
