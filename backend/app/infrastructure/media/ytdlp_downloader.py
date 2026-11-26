import asyncio
import logging
import os
import re
from urllib.parse import urlparse

from yt_dlp.networking import Request
from yt_dlp.utils import DownloadError, GeoRestrictedError

from ...domain.entities import MediaSlide, SavedUpload, SlideKind, SourceMetadata
from ...domain.entitlements import MediaLimits, size_over_limit_message
from ...domain.errors import MediaValidationError
from ..config import Settings
from .deadline import DownloadDeadline, DownloadDeadlineExceeded, run_download
from .ffmpeg import _media_binary
from .limits import effective_limits
from .net import validate_public_url
from .thumbnails import dimensions_from_info, thumbnail_urls_from_info
from .uploads import _cleanup_dir, create_run_dir
from .ytdlp_net import GuardedYoutubeDL

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

logger = logging.getLogger("videolens")


def _cookie_options(settings: Settings) -> dict:
    cookie_file = settings.ytdlp_cookies_file.strip()
    browser = settings.ytdlp_cookies_from_browser.strip().lower()
    if cookie_file and browser:
        raise MediaValidationError(
            "This link couldn't be downloaded.",
            log_detail=(
                "Configure only one yt-dlp cookie source: YTDLP_COOKIES_FILE or "
                "YTDLP_COOKIES_FROM_BROWSER, not both."
            ),
        )
    if cookie_file:
        resolved = os.path.abspath(os.path.expanduser(cookie_file))
        if not os.path.isfile(resolved):
            raise MediaValidationError(
                "This link couldn't be downloaded.",
                log_detail=f"YTDLP_COOKIES_FILE points at {resolved!r}, which does not exist.",
            )
        return {"cookiefile": resolved}
    if browser:
        return {"cookiesfrombrowser": (browser, None, None, None)}
    return {}


# Separate video+audio first (how YouTube serves anything above 360p), then a
# single progressive file (Instagram/TikTok mp4), then audio alone (podcast and
# SoundCloud-style sources). The selector only says *which kind* of format; the
# size cap lives in format_sort so it can never reject a source outright.
_FORMAT_SELECTOR = "bestvideo*+bestaudio/best/bestaudio"


def _format_options(settings: Settings) -> dict:
    """yt-dlp format options, capped at YTDLP_MAX_HEIGHT.

    `format_sort: ["res:N"]` rather than a `[height<=N]` filter in the
    selector: the sort prefers the largest variant at or under N and, when a
    source has none, the *smallest* one above it - whereas a filter with a
    `/bv*+ba/b` fallback would jump straight to the source's best (4K) in that
    case, and `[height<=N]` silently drops formats whose height yt-dlp doesn't
    know (common on progressive social-media mp4s). Every other sort key keeps
    yt-dlp's default order, so audio-only sources are untouched.
    """
    options: dict = {"format": _FORMAT_SELECTOR}
    if settings.ytdlp_max_height > 0:
        options["format_sort"] = [f"res:{settings.ytdlp_max_height}"]
    return options


def _source_metadata_from_info(info: dict, url: str) -> SourceMetadata:
    """Map yt-dlp's info dict onto the domain model.

    Shared with the caption fallback, which reaches the same dict through
    `extract_info(download=False)` - the publisher's own post metadata is
    available whether or not the media bytes are.
    """
    return SourceMetadata(
        platform=info.get("extractor_key") or "unknown",
        source_url=url,
        title=info.get("title"),
        uploader=info.get("uploader"),
        uploader_url=info.get("uploader_url"),
        description=info.get("description"),
        upload_date=info.get("upload_date"),
        like_count=info.get("like_count"),
        view_count=info.get("view_count"),
        comment_count=info.get("comment_count"),
    )


# Cause plus timing only: the frontend's recoveryAdvice for the `downloading`
# stage already offers "download the video and upload the file instead", so
# repeating that here would print it twice (docs/error-messaging.md).
_BLOCKED_DOWNLOAD = (
    "The site blocked this download for now - the video itself is fine. Try again "
    "in a few minutes."
)

_REGION_LOCKED = "This video isn't available in this server's region."

# Matched against yt-dlp's own wording. Each entry turns one recognised failure
# into a sentence that names the cause in the user's terms — the raw text goes
# to the log instead, because it is written for whoever runs yt-dlp ("use
# --cookies-from-browser", "Confirm you are on the latest version using
# yt-dlp -U") and reaches someone holding a phone.
_KNOWN_DOWNLOAD_FAILURES = (
    (
        "Instagram sent an empty media response",
        "This post isn't public - Instagram only serves it to signed-in viewers.",
    ),
    (
        "Sign in to confirm you",
        "YouTube is blocking automated downloads from this server.",
    ),
    (
        "This video is private",
        "This video is private.",
    ),
    # Geo-blocks, in yt-dlp's real wording (yt-dlp 2026.07.04). Ahead of "Video
    # unavailable" and well ahead of the 403/429 entries: a geo-blocked video can
    # also surface an HTTP 403, and the region is the true cause.
    *(
        (marker, _REGION_LOCKED)
        for marker in (
            # YouTube's subreason, passed to raise_geo_restricted
            # (extractor/youtube/_video.py).
            "available in your country",
            # raise_geo_restricted's default message (extractor/common.py).
            "not available from your location",
            "due to geo restriction",
            # Appended by YoutubeDL to every GeoRestrictedError it reports
            # (YoutubeDL.py), whatever message the extractor chose.
            "You might want to use a VPN or a proxy server",
        )
    ),
    (
        "Video unavailable",
        "This video is no longer available.",
    ),
    # Throttling / bot-blocking, typically partway through a public video's
    # download. Checked after the private/deleted/region markers so a genuine
    # one of those keeps its own sentence; before this entry existed a 403 fell
    # through to the generic "may be private, deleted" text, which was untrue.
    *(
        (marker, _BLOCKED_DOWNLOAD)
        for marker in ("HTTP Error 403", "HTTP Error 429", "Too Many Requests")
    ),
)

_GENERIC_DOWNLOAD_FAILURE = (
    "This link couldn't be downloaded. It may be private, deleted, or region-locked."
)


_TOO_SLOW_DOWNLOAD = "This link took too long to download. Try again, or upload the file instead."


def _download_failure(exc: DownloadError) -> tuple[str, str]:
    """Split one yt-dlp failure into (what the user sees, what the log gets)."""
    detail = ANSI_ESCAPE.sub("", str(exc)).removeprefix("ERROR: ")
    # yt-dlp keeps the original exception in exc_info; the type settles a
    # geo-block even when an extractor words its message in its own way.
    exc_info = getattr(exc, "exc_info", None) or (None, None, None)
    if isinstance(exc_info[1], GeoRestrictedError):
        return _REGION_LOCKED, detail
    for marker, message in _KNOWN_DOWNLOAD_FAILURES:
        if marker in detail:
            return message, detail
    return _GENERIC_DOWNLOAD_FAILURE, detail


# ---------------------------------------------------------------- slides
#
# An Instagram carousel is one post made of up to 20 slides, each a video or a
# still image. Only Instagram links take this path: any other site's playlist
# stops after its first entry (`playlistend` 1) and is refused with
# `_PLAYLIST_LINK`, unless it holds exactly one entry, which is just a video.
# yt-dlp's own playlist processing downloads the video slides, each to its own
# file through the template below; image slides have no formats, so on
# Instagram they are let through extraction (`ignore_no_formats_error`) and
# skipped at download time (`_skip_entries_without_media`), and their image -
# the entry's largest thumbnail - is fetched here through the same guarded
# `urlopen`, inside the same deadline and byte budget.

# Instagram's own limit for one carousel.
MAX_SLIDES = 20

# One image slide, read whole. Instagram's largest are a megabyte or two.
MAX_IMAGE_SLIDE_BYTES = 15 * 1024 * 1024

_READ_CHUNK_BYTES = 64 * 1024

# A playlist entry (one slide of a post) is `slide-01.<ext>`, `slide-02.<ext>`
# and so on, numbered by its place in the post; a single media file keeps the
# `download.<ext>` it always had.
_OUTTMPL = "%(playlist_index&slide-{:02d}|download)s.%(ext)s"

_PLAYLIST_TYPES = ("playlist", "multi_video")

_UNREADABLE_SLIDE = "A slide in this post couldn't be read."
_NOTHING_TO_ANALYZE = "This post has no video or image we could download."
# Any other site's playlist, set or multi-part link. Slides are an Instagram
# idea: a SoundCloud set or a YouTube playlist is not one post, and running it
# as one would download up to MAX_SLIDES files and label audio as video.
_PLAYLIST_LINK = "This link is a playlist or set. Paste a link to one video or track instead."


def _is_instagram(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "instagram.com" or host.endswith(".instagram.com")


def _skip_entries_without_media(info: dict, *, incomplete: bool = False) -> str | None:
    """yt-dlp `match_filter`. An Instagram image slide reaches the download
    step with no media URL, where yt-dlp would raise "No video formats found"
    and abort the whole post; skipping it there keeps its info (and its
    thumbnails, which are the image) in the result instead. Only installed
    for Instagram links."""
    if incomplete or info.get("url") or info.get("requested_formats"):
        return None
    return "no media to download (an image slide)"


def _downloaded_file(entry: dict) -> str | None:
    requested = entry.get("requested_downloads") or []
    candidates = [item.get("filepath") for item in requested if isinstance(item, dict)]
    candidates.append(entry.get("filepath"))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _image_url(entry: dict) -> str | None:
    """The full-size image behind an image slide: the largest thumbnail
    (Instagram lists every rendition of the photo), else yt-dlp's pick."""
    best: tuple[int, str] | None = None
    for thumbnail in entry.get("thumbnails") or []:
        if not isinstance(thumbnail, dict):
            continue
        url = thumbnail.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        try:
            area = int(thumbnail.get("width") or 0) * int(thumbnail.get("height") or 0)
        except (TypeError, ValueError):
            area = 0
        if best is None or area >= best[0]:
            best = (area, url)
    if best is not None:
        return best[1]
    url = entry.get("thumbnail")
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None


def _is_image_entry(entry: dict) -> bool:
    """An image slide (or a single-image post): nothing was downloaded, the
    entry is not timed media, and there is a picture to fetch."""
    return (
        _downloaded_file(entry) is None
        and not entry.get("formats")
        and not entry.get("duration")
        and _image_url(entry) is not None
    )


def _image_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _fetch_image(
    downloader,
    url: str,
    headers: dict | None,
    stem: str,
    budget_bytes: int,
    deadline: DownloadDeadline,
    over_limit: str,
) -> tuple[str, int]:
    """Fetch one image slide to `stem` + its real extension. Through the
    downloader's `urlopen`, so on `net.py`'s pinned connections (the SSRF
    guard), with its cookies and under the run's deadline."""
    limit = min(MAX_IMAGE_SLIDE_BYTES, budget_bytes)
    if limit <= 0:
        raise DownloadError(over_limit)
    request_headers = {key: value for key, value in (headers or {}).items() if isinstance(value, str)}
    response = downloader.urlopen(Request(url, headers=request_headers))
    chunks: list[bytes] = []
    size = 0
    try:
        while True:
            deadline.check()
            chunk = response.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                if limit < budget_bytes:
                    raise MediaValidationError(
                        _UNREADABLE_SLIDE,
                        log_detail=f"an image slide is over {MAX_IMAGE_SLIDE_BYTES // (1024 * 1024)} MB",
                    )
                raise DownloadError(over_limit)
            chunks.append(chunk)
    finally:
        response.close()
    data = b"".join(chunks)
    extension = _image_extension(data)
    if extension is None:
        raise MediaValidationError(
            _UNREADABLE_SLIDE,
            log_detail=f"an image slide is not JPEG, PNG or WebP (first bytes {data[:12]!r})",
        )
    path = stem + extension
    with open(path, "wb") as fh:
        fh.write(data)
    return path, size


def _is_multi_slide(info: dict) -> bool:
    """For an Instagram link: a carousel, or a post that is one photo (no
    playlist, nothing downloaded)."""
    return info.get("_type") in _PLAYLIST_TYPES or _is_image_entry(info)


def _single_entry_of(info: dict) -> tuple[str, dict]:
    """Another site's playlist: its one downloaded entry when the playlist
    holds exactly one (some extractors wrap a single video that way), else
    refused. Only the first entry was downloaded (`playlistend` 1)."""
    entries = [entry for entry in info.get("entries") or [] if isinstance(entry, dict)]
    path = _downloaded_file(entries[0]) if entries else None
    if info.get("playlist_count") == 1 and path is not None:
        return path, entries[0]
    raise MediaValidationError(
        _PLAYLIST_LINK,
        log_detail=(
            f"{info.get('extractor_key') or 'unknown'} returned a {info.get('_type')} "
            f"of {info.get('playlist_count')} entries"
        ),
    )


def _collect_slides(
    downloader,
    info: dict,
    run_dir: str,
    deadline: DownloadDeadline,
    max_bytes: int,
    over_limit: str,
) -> tuple[tuple[MediaSlide, ...], dict]:
    """The post's slides in order, and the info dict of the first one (its
    poster hints). Video slides are already on disk; image slides are
    fetched now. An entry with neither is skipped and logged."""
    if info.get("_type") in _PLAYLIST_TYPES:
        entries = [entry for entry in info.get("entries") or [] if isinstance(entry, dict)]
    else:
        entries = [info]
    slides: list[MediaSlide] = []
    first: dict | None = None
    spent = 0
    for position, entry in enumerate(entries[:MAX_SLIDES], start=1):
        index = entry.get("playlist_index") if isinstance(entry.get("playlist_index"), int) else position
        path = _downloaded_file(entry)
        if path is not None:
            slides.append(MediaSlide(path=path, kind=SlideKind.VIDEO))
            spent += os.path.getsize(path)
        elif _is_image_entry(entry):
            image_path, size = _fetch_image(
                downloader,
                _image_url(entry) or "",
                entry.get("http_headers"),
                os.path.join(run_dir, f"slide-{index:02d}"),
                max_bytes - spent,
                deadline,
                over_limit,
            )
            slides.append(MediaSlide(path=image_path, kind=SlideKind.IMAGE))
            spent += size
        else:
            logger.warning("Slide %s of a post had nothing to download; skipped", index)
            continue
        if first is None:
            first = entry
    if len(entries) > MAX_SLIDES:
        logger.warning("A post had %d slides; only the first %d were kept", len(entries), MAX_SLIDES)
    return tuple(slides), first or info


async def download_url(
    settings: Settings, run_id: str, url: str, limits: MediaLimits | None = None
) -> SavedUpload:
    limits = effective_limits(settings, limits)
    await asyncio.to_thread(validate_public_url, url)
    cookie_options = _cookie_options(settings)
    ffmpeg_path = _media_binary(settings, "ffmpeg")
    run_dir = create_run_dir(settings, run_id)
    max_bytes = limits.max_file_size_bytes
    over_limit = f"The video is over the {limits.max_file_size_mb}MB limit."
    instagram = _is_instagram(url)

    def fetch(deadline: DownloadDeadline) -> tuple[str, dict, tuple[MediaSlide, ...], dict]:
        # Bytes so far per file being written: a post's slides (and a video's
        # split streams) share one size cap, as they share one run.
        written: dict[str, int] = {}

        def progress_hook(status: dict) -> None:
            # Called for every chunk and fragment: the wall-clock bound
            # first, then the size cap.
            deadline.check()
            written[status.get("filename") or ""] = status.get("downloaded_bytes") or 0
            if sum(written.values()) > max_bytes:
                raise DownloadError(over_limit)

        options = {
            **_format_options(settings),
            "outtmpl": os.path.join(run_dir, _OUTTMPL),
            "noplaylist": True,
            # A carousel's slides; anything else only needs its first entry
            # to be told apart from a playlist (`_single_entry_of`).
            "playlistend": MAX_SLIDES if instagram else 1,
            "max_filesize": max_bytes,
            "socket_timeout": 30,
            "retries": 2,
            "fragment_retries": 2,
            "restrictfilenames": True,
            "quiet": True,
            "no_warnings": True,
            "cachedir": False,
            "ffmpeg_location": os.path.dirname(ffmpeg_path),
            "progress_hooks": [progress_hook],
            **cookie_options,
        }
        if instagram:
            # Image slides and single-photo posts: see the slides section.
            options["ignore_no_formats_error"] = True
            options["match_filter"] = _skip_entries_without_media
        with GuardedYoutubeDL(options, deadline=deadline) as downloader:
            info = downloader.extract_info(url, download=True)
            # A deadline that fired mid-read can surface as a short read
            # yt-dlp accepted; a cut-off file is not a download.
            deadline.check()
            if not instagram and info.get("_type") in _PLAYLIST_TYPES:
                path, entry = _single_entry_of(info)
                return path, info, (), entry
            if instagram and _is_multi_slide(info):
                slides, first = _collect_slides(
                    downloader, info, run_dir, deadline, max_bytes, over_limit
                )
                deadline.check()
                if not slides:
                    raise MediaValidationError(
                        _NOTHING_TO_ANALYZE, log_detail="every entry of the post was skipped"
                    )
                if len(slides) == 1 and slides[0].kind is SlideKind.VIDEO:
                    # A one-video "post": exactly the single-file pipeline.
                    return slides[0].path, info, (), first
                return slides[0].path, info, slides, first
            requested = info.get("requested_downloads") or []
            candidates = [item.get("filepath") for item in requested if item.get("filepath")]
            candidates.append(info.get("filepath"))
            candidates.append(downloader.prepare_filename(info))
            for candidate in candidates:
                if candidate and os.path.isfile(candidate):
                    return candidate, info, (), info
        raise DownloadError("The downloaded media file could not be found.")

    try:
        path, info, slides, first = await run_download(
            settings.download_deadline_seconds, fetch, run_budget=True
        )
        if slides:
            size_bytes = sum(os.path.getsize(slide.path) for slide in slides)
        else:
            size_bytes = os.path.getsize(path)
        if size_bytes > max_bytes:
            raise MediaValidationError(
                size_over_limit_message(limits, subject="That post" if slides else "That video")
            )
        metadata = _source_metadata_from_info(info, url)
        # The poster hints come from the first slide: the post's own cover.
        width, height = dimensions_from_info(first)
        return SavedUpload(
            path=path,
            run_dir=run_dir,
            metadata=metadata,
            thumbnail_urls=thumbnail_urls_from_info(first),
            width=width,
            height=height,
            size_bytes=size_bytes,
            slides=slides,
        )
    except MediaValidationError:
        _cleanup_dir(run_dir)
        raise
    except DownloadDeadlineExceeded as exc:
        _cleanup_dir(run_dir)
        raise MediaValidationError(_TOO_SLOW_DOWNLOAD, log_detail=f"yt-dlp deadline: {exc}") from exc
    except DownloadError as exc:
        _cleanup_dir(run_dir)
        message, detail = _download_failure(exc)
        raise MediaValidationError(message, log_detail=detail) from exc
    except Exception as exc:
        _cleanup_dir(run_dir)
        raise MediaValidationError(
            _GENERIC_DOWNLOAD_FAILURE, log_detail=f"{type(exc).__name__}: {exc}"
        ) from exc
