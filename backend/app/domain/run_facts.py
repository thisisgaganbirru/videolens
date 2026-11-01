"""Facts about a run's *media* that the history grid shows, derived from what
the run already stores.

Pure functions, no I/O. They live here rather than in the route so the
derivation has one home and one set of tests, and so a run stored before these
fields existed still gets a sensible answer: every input may be missing, and
every output may be None.

Nothing here describes the person who submitted the run - only the source
(which platform, how long, which way up) and the analysis's own summary.
"""

import re
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import urlparse

from .entities import Run, SourceMetadata

SourceKind = Literal["link", "file"]
Orientation = Literal["landscape", "portrait"]

PLATFORM_YOUTUBE = "youtube"
PLATFORM_INSTAGRAM = "instagram"
PLATFORM_TIKTOK = "tiktok"
PLATFORM_AUDIO_FILE = "audio_file"
PLATFORM_VIDEO_FILE = "video_file"
PLATFORM_OTHER = "other"

KNOWN_PLATFORMS = frozenset(
    {
        PLATFORM_YOUTUBE,
        PLATFORM_INSTAGRAM,
        PLATFORM_TIKTOK,
        PLATFORM_AUDIO_FILE,
        PLATFORM_VIDEO_FILE,
        PLATFORM_OTHER,
    }
)

SNIPPET_MAX_CHARS = 160

_AUDIO_EXTENSIONS = frozenset({".mp3"})

# Ordered: yt-dlp's extractor key is checked by prefix, so "YoutubeTab" and
# "TikTokLive" fold into their platform without listing every variant.
_EXTRACTOR_PREFIXES: tuple[tuple[str, str], ...] = (
    ("youtube", PLATFORM_YOUTUBE),
    ("instagram", PLATFORM_INSTAGRAM),
    ("tiktok", PLATFORM_TIKTOK),
)

_HOST_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("youtube.com", PLATFORM_YOUTUBE),
    ("youtu.be", PLATFORM_YOUTUBE),
    ("youtube-nocookie.com", PLATFORM_YOUTUBE),
    ("instagram.com", PLATFORM_INSTAGRAM),
    ("tiktok.com", PLATFORM_TIKTOK),
)

_WHITESPACE = re.compile(r"\s+")


def _host(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url.strip()).hostname or ""
    except ValueError:
        return ""
    return host.lower()


def _host_platform(url: Optional[str]) -> Optional[str]:
    host = _host(url)
    if not host:
        return None
    for suffix, platform in _HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return platform
    return None


def link_platform(extractor_key: Optional[str], url: Optional[str]) -> str:
    """Normalize a link run's platform. yt-dlp's extractor key wins; the URL
    host is the fallback (e.g. the direct-HTTP resolver reports no extractor);
    anything unrecognised is "other"."""
    key = (extractor_key or "").strip().lower()
    for prefix, platform in _EXTRACTOR_PREFIXES:
        if key.startswith(prefix):
            return platform
    return _host_platform(url) or PLATFORM_OTHER


def file_platform(extension: Optional[str]) -> str:
    """Platform for an uploaded file, from its extension alone (".mp3" ->
    audio). Takes the extension, never the filename, which can carry personal
    information and is deliberately not stored."""
    ext = (extension or "").strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return PLATFORM_AUDIO_FILE if ext in _AUDIO_EXTENSIONS else PLATFORM_VIDEO_FILE


def resolve_source_kind(
    source_kind: Optional[str], metadata: Optional[SourceMetadata]
) -> Optional[SourceKind]:
    """The stored kind, or for a run stored before it was recorded: "link" if
    yt-dlp metadata is present (only URL runs ever get it), otherwise unknown."""
    if source_kind in ("link", "file"):
        return source_kind  # type: ignore[return-value]
    if metadata is not None:
        return "link"
    return None


def resolve_platform(
    source_kind: Optional[str],
    stored_platform: Optional[str],
    metadata: Optional[SourceMetadata],
) -> Optional[str]:
    if stored_platform in KNOWN_PLATFORMS:
        return stored_platform
    kind = resolve_source_kind(source_kind, metadata)
    if kind == "link":
        if metadata is None:
            # A link run whose metadata never arrived (download failed with no
            # caption fallback). The URL was not stored, so there is nothing
            # left to infer from.
            return None
        return link_platform(metadata.platform, metadata.source_url)
    return None


def _is_youtube_shorts(url: Optional[str]) -> bool:
    if not url:
        return False
    try:
        path = urlparse(url.strip()).path or ""
    except ValueError:
        return False
    return path.lower().startswith("/shorts/")


def resolve_orientation(
    platform: Optional[str], source_url: Optional[str]
) -> Optional[Orientation]:
    """A poster-shape hint, not a measurement: YouTube watch URLs are
    landscape, YouTube Shorts and every other known platform portrait."""
    if platform is None:
        return None
    if platform == PLATFORM_YOUTUBE:
        if not source_url:
            return None
        return "portrait" if _is_youtube_shorts(source_url) else "landscape"
    return "portrait"


def summary_snippet(summary: Optional[str], limit: int = SNIPPET_MAX_CHARS) -> Optional[str]:
    """Whitespace-collapsed summary, cut at a word boundary to at most `limit`
    characters (ellipsis included) when it is longer."""
    if not summary:
        return None
    text = _WHITESPACE.sub(" ", summary).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    budget = limit - 1  # room for the ellipsis
    cut = text[: budget + 1]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    else:
        cut = text[:budget]
    return cut.rstrip(" ,;:.-") + "…"


@dataclass(frozen=True)
class RunFacts:
    source_kind: Optional[SourceKind]
    platform: Optional[str]
    duration_seconds: Optional[float]
    orientation: Optional[Orientation]
    summary_snippet: Optional[str]


def describe_run(run: Run) -> RunFacts:
    metadata = run.source_metadata
    kind = resolve_source_kind(run.source_kind, metadata)
    platform = resolve_platform(run.source_kind, run.platform, metadata)
    return RunFacts(
        source_kind=kind,
        platform=platform,
        duration_seconds=run.duration_seconds,
        orientation=resolve_orientation(
            platform, metadata.source_url if metadata else None
        ),
        summary_snippet=summary_snippet(run.result.summary if run.result else None),
    )
