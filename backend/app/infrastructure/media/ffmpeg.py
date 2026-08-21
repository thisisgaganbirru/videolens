import asyncio
import os
import shutil

from ...domain.errors import MediaValidationError
from ..config import Settings
from .uploads import cleanup_run_dir


def _media_binary(settings: Settings, name: str) -> str:
    configured = settings.ffmpeg_location.strip()
    executable = f"{name}.exe" if os.name == "nt" else name

    if configured:
        location = os.path.abspath(os.path.expanduser(configured))
        directory = location if os.path.isdir(location) else os.path.dirname(location)
        candidate = os.path.join(directory, executable)
        if os.path.isfile(candidate):
            return candidate
        raise MediaValidationError(
            "This file couldn't be processed.",
            log_detail=f"{name} was not found in the configured FFMPEG_LOCATION directory.",
        )

    discovered = shutil.which(name)
    if discovered:
        return discovered
    raise MediaValidationError(
        "This file couldn't be processed.",
        log_detail=(
            f"{name} is not on PATH and FFMPEG_LOCATION is unset. Install FFmpeg or "
            "set FFMPEG_LOCATION."
        ),
    )


def validate_media_tools(settings: Settings) -> None:
    _media_binary(settings, "ffmpeg")
    _media_binary(settings, "ffprobe")


def _clock(seconds: float) -> str:
    """`m:ss`, matching how the frontend prints every other timestamp. "240s
    exceeds the 180s limit" is a measurement; "4:00, the limit is 3:00" is the
    same fact in the units the person was looking at."""
    total = max(0, round(seconds))
    return f"{total // 60}:{total % 60:02d}"


async def probe_duration_seconds(settings: Settings, path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        _media_binary(settings, "ffprobe"),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0 or not stdout.strip():
        raise MediaValidationError(
            "This file couldn't be read. It may be corrupted or in a format we don't support.",
            log_detail=(
                f"ffprobe exited {proc.returncode}: "
                + stderr.decode(errors="ignore")[-500:]
            ),
        )
    try:
        return float(stdout.strip())
    except ValueError as exc:
        raise MediaValidationError(
            "This file couldn't be read. It may be corrupted or in a format we don't support.",
            log_detail=f"ffprobe returned an unparseable duration: {stdout!r}",
        ) from exc


async def enforce_duration_cap(settings: Settings, run_id: str, path: str) -> None:
    try:
        duration = await probe_duration_seconds(settings, path)
    except MediaValidationError:
        cleanup_run_dir(settings, run_id)
        raise
    if duration > settings.max_duration_seconds:
        cleanup_run_dir(settings, run_id)
        raise MediaValidationError(
            f"This video is {_clock(duration)} long. The limit is "
            f"{_clock(settings.max_duration_seconds)}."
        )


async def _has_video_stream(settings: Settings, path: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        _media_binary(settings, "ffprobe"),
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


async def normalize_media(settings: Settings, src_path: str, run_dir: str) -> str:
    if await _has_video_stream(settings, src_path):
        normalized_path = os.path.join(run_dir, "normalized.mp4")
        command = [
            _media_binary(settings, "ffmpeg"), "-y", "-i", src_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart", normalized_path,
        ]
    else:
        normalized_path = os.path.join(run_dir, "normalized.mp3")
        command = [
            _media_binary(settings, "ffmpeg"), "-y", "-i", src_path,
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
            "This file couldn't be processed.",
            log_detail=(
                f"ffmpeg exited {proc.returncode}: "
                + stderr.decode(errors="ignore")[-2000:]
            ),
        )
    return normalized_path
