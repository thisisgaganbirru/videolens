import asyncio
import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from ...domain.entities import SavedUpload, SourceMetadata
from ...domain.errors import MediaValidationError
from ..config import Settings
from .ffmpeg import _media_binary
from .uploads import _cleanup_dir, create_run_dir

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _validate_public_url(url: str) -> None:
    if len(url) > 2048:
        raise MediaValidationError("That link is too long.")

    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise MediaValidationError("Enter a valid public http:// or https:// link.")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, ValueError) as exc:
        raise MediaValidationError(
            "That link's site couldn't be found - check for a typo.", log_detail=str(exc)
        ) from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise MediaValidationError("That link points to a private network address.")


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
    (
        "Video unavailable",
        "This video is no longer available.",
    ),
    (
        "not available in your country",
        "This video isn't available in this server's region.",
    ),
)

_GENERIC_DOWNLOAD_FAILURE = (
    "This link couldn't be downloaded. It may be private, deleted, or region-locked."
)


def _download_failure(exc: DownloadError) -> tuple[str, str]:
    """Split one yt-dlp failure into (what the user sees, what the log gets)."""
    detail = ANSI_ESCAPE.sub("", str(exc)).removeprefix("ERROR: ")
    for marker, message in _KNOWN_DOWNLOAD_FAILURES:
        if marker in detail:
            return message, detail
    return _GENERIC_DOWNLOAD_FAILURE, detail


async def download_url(settings: Settings, run_id: str, url: str) -> SavedUpload:
    await asyncio.to_thread(_validate_public_url, url)
    cookie_options = _cookie_options(settings)
    ffmpeg_path = _media_binary(settings, "ffmpeg")
    run_dir = create_run_dir(settings, run_id)
    max_bytes = settings.max_file_size_mb * 1024 * 1024

    def progress_hook(status: dict) -> None:
        downloaded = status.get("downloaded_bytes") or 0
        if downloaded > max_bytes:
            raise DownloadError(f"The video is over the {settings.max_file_size_mb}MB limit.")

    def run_download() -> tuple[str, dict]:
        options = {
            "format": "bestvideo*+bestaudio/best/bestaudio",
            "outtmpl": os.path.join(run_dir, "download.%(ext)s"),
            "noplaylist": True,
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
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            requested = info.get("requested_downloads") or []
            candidates = [item.get("filepath") for item in requested if item.get("filepath")]
            candidates.append(info.get("filepath"))
            candidates.append(downloader.prepare_filename(info))
            for candidate in candidates:
                if candidate and os.path.isfile(candidate):
                    return candidate, info
        raise DownloadError("The downloaded media file could not be found.")

    try:
        path, info = await asyncio.to_thread(run_download)
        if os.path.getsize(path) > max_bytes:
            raise MediaValidationError(
                f"Download exceeds the {settings.max_file_size_mb}MB size limit."
            )
        metadata = SourceMetadata(
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
        return SavedUpload(path=path, run_dir=run_dir, metadata=metadata)
    except MediaValidationError:
        _cleanup_dir(run_dir)
        raise
    except DownloadError as exc:
        _cleanup_dir(run_dir)
        message, detail = _download_failure(exc)
        raise MediaValidationError(message, log_detail=detail) from exc
    except Exception as exc:
        _cleanup_dir(run_dir)
        raise MediaValidationError(
            _GENERIC_DOWNLOAD_FAILURE, log_detail=f"{type(exc).__name__}: {exc}"
        ) from exc
