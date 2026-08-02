import asyncio
import ipaddress
import os
import re
import shutil
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import UploadFile
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .config import settings


class MediaValidationError(Exception):
    pass


# Preserve compatibility for code importing the previous exception name.
VideoValidationError = MediaValidationError

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass
class SavedUpload:
    path: str
    run_dir: str


def _run_temp_dir(run_id: str) -> str:
    path = os.path.join(settings.temp_dir, run_id)
    os.makedirs(path, exist_ok=True)
    return path


def _cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def cleanup_run_dir(run_id: str) -> None:
    _cleanup_dir(os.path.join(settings.temp_dir, run_id))


def _media_binary(name: str) -> str:
    configured = settings.ffmpeg_location.strip()
    executable = f"{name}.exe" if os.name == "nt" else name

    if configured:
        location = os.path.abspath(os.path.expanduser(configured))
        directory = location if os.path.isdir(location) else os.path.dirname(location)
        candidate = os.path.join(directory, executable)
        if os.path.isfile(candidate):
            return candidate
        raise MediaValidationError(
            f"{name} was not found in the configured FFMPEG_LOCATION directory."
        )

    discovered = shutil.which(name)
    if discovered:
        return discovered
    raise MediaValidationError(
        "FFmpeg is not available to the backend. Install FFmpeg or configure FFMPEG_LOCATION."
    )


def validate_media_tools() -> None:
    _media_binary("ffmpeg")
    _media_binary("ffprobe")


async def save_upload(run_id: str, upload: UploadFile) -> SavedUpload:
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in settings.allowed_extensions:
        raise MediaValidationError(
            f"Unsupported file type '{ext or 'unknown'}'. Only .mp3, .mp4, and .mov are accepted."
        )

    run_dir = _run_temp_dir(run_id)
    dest_path = os.path.join(run_dir, f"upload{ext}")
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    chunk_size = 1024 * 1024

    total = 0
    try:
        with open(dest_path, "wb") as out_file:
            while chunk := await upload.read(chunk_size):
                total += len(chunk)
                if total > max_bytes:
                    raise MediaValidationError(
                        f"File exceeds the {settings.max_file_size_mb}MB size limit."
                    )
                out_file.write(chunk)
    except MediaValidationError:
        _cleanup_dir(run_dir)
        raise
    finally:
        await upload.close()

    if total == 0:
        _cleanup_dir(run_dir)
        raise MediaValidationError("Uploaded file is empty.")

    return SavedUpload(path=dest_path, run_dir=run_dir)


async def probe_duration_seconds(path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        _media_binary("ffprobe"),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0 or not stdout.strip():
        raise MediaValidationError(
            "Could not read the media file. It may be corrupted or in an unsupported format."
        )
    try:
        return float(stdout.strip())
    except ValueError as exc:
        raise MediaValidationError("Could not determine media duration.") from exc


async def enforce_duration_cap(run_id: str, path: str) -> None:
    try:
        duration = await probe_duration_seconds(path)
    except MediaValidationError:
        cleanup_run_dir(run_id)
        raise
    if duration > settings.max_duration_seconds:
        cleanup_run_dir(run_id)
        raise MediaValidationError(
            f"Media is {duration:.0f}s long, which exceeds the "
            f"{settings.max_duration_seconds}s limit."
        )


def _validate_public_url(url: str) -> None:
    if len(url) > 2048:
        raise MediaValidationError("URL is too long.")

    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise MediaValidationError("Enter a valid public HTTP or HTTPS media URL.")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, ValueError) as exc:
        raise MediaValidationError("The URL host could not be found.") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise MediaValidationError("Local and private-network URLs are not allowed.")


def _cookie_options() -> dict:
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


async def download_url(run_id: str, url: str) -> SavedUpload:
    await asyncio.to_thread(_validate_public_url, url)
    cookie_options = _cookie_options()
    ffmpeg_path = _media_binary("ffmpeg")
    run_dir = _run_temp_dir(run_id)
    max_bytes = settings.max_file_size_mb * 1024 * 1024

    def progress_hook(status: dict) -> None:
        downloaded = status.get("downloaded_bytes") or 0
        if downloaded > max_bytes:
            raise DownloadError(f"Download exceeds the {settings.max_file_size_mb}MB size limit.")

    def run_download() -> str:
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
                    return candidate
        raise DownloadError("The downloaded media file could not be found.")

    try:
        path = await asyncio.to_thread(run_download)
        if os.path.getsize(path) > max_bytes:
            raise MediaValidationError(
                f"Download exceeds the {settings.max_file_size_mb}MB size limit."
            )
        return SavedUpload(path=path, run_dir=run_dir)
    except MediaValidationError:
        _cleanup_dir(run_dir)
        raise
    except DownloadError as exc:
        _cleanup_dir(run_dir)
        raise MediaValidationError(_download_error_message(exc)) from exc
    except Exception as exc:
        _cleanup_dir(run_dir)
        raise MediaValidationError("Could not download media from this URL.") from exc


async def _has_video_stream(path: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        _media_binary("ffprobe"),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode == 0 and stdout.strip() == b"video"


async def normalize_media(src_path: str, run_dir: str) -> str:
    if await _has_video_stream(src_path):
        normalized_path = os.path.join(run_dir, "normalized.mp4")
        command = [
            _media_binary("ffmpeg"), "-y", "-i", src_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart", normalized_path,
        ]
    else:
        normalized_path = os.path.join(run_dir, "normalized.mp3")
        command = [
            _media_binary("ffmpeg"), "-y", "-i", src_path,
            "-vn", "-c:a", "libmp3lame", "-b:a", "192k", normalized_path,
        ]

    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise MediaValidationError(
            "Failed to process media file: " + stderr.decode(errors="ignore")[-500:]
        )
    return normalized_path


normalize_video = normalize_media
