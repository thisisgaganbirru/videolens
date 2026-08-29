import asyncio
import os
import re

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from ...domain.entities import SavedUpload, SourceMetadata
from ...domain.errors import MediaValidationError
from ..config import Settings
from .ffmpeg import _media_binary
from .net import validate_public_url
from .uploads import _cleanup_dir, create_run_dir

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _cookie_options(settings: Settings) -> dict:
    cookie_file = settings.ytdlp_cookies_file.strip()
    browser = settings.ytdlp_cookies_from_browser.strip().lower()
    if cookie_file and browser:
        raise MediaValidationError(
            "Configure only one yt-dlp cookie source: a cookie file or a browser."
        )
    if cookie_file:
        resolved = os.path.abspath(os.path.expanduser(cookie_file))
        if not os.path.isfile(resolved):
            raise MediaValidationError("The configured yt-dlp cookie file was not found.")
        return {"cookiefile": resolved}
    if browser:
        return {"cookiesfrombrowser": (browser, None, None, None)}
    return {}


def _download_error_message(exc: DownloadError) -> str:
    message = ANSI_ESCAPE.sub("", str(exc)).removeprefix("ERROR: ")
    if "Instagram sent an empty media response" in message:
        return (
            "Instagram did not return media for this request. The post may require login "
            "cookies, or Instagram may be blocking logged-out downloads. Configure "
            "YTDLP_COOKIES_FROM_BROWSER for local use or YTDLP_COOKIES_FILE on the server."
        )
    return f"Could not download media from this URL. {message}"


async def download_url(settings: Settings, run_id: str, url: str) -> SavedUpload:
    await asyncio.to_thread(validate_public_url, url)
    cookie_options = _cookie_options(settings)
    ffmpeg_path = _media_binary(settings, "ffmpeg")
    run_dir = create_run_dir(settings, run_id)
    max_bytes = settings.max_file_size_mb * 1024 * 1024

    def progress_hook(status: dict) -> None:
        downloaded = status.get("downloaded_bytes") or 0
        if downloaded > max_bytes:
            raise DownloadError(f"Download exceeds the {settings.max_file_size_mb}MB size limit.")

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
        raise MediaValidationError(_download_error_message(exc)) from exc
    except Exception as exc:
        _cleanup_dir(run_dir)
        raise MediaValidationError("Could not download media from this URL.") from exc
