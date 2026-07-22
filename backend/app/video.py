import asyncio
import os
import shutil
from dataclasses import dataclass

from fastapi import UploadFile

from .config import settings


class VideoValidationError(Exception):
    pass


@dataclass
class SavedUpload:
    path: str
    job_dir: str


def _job_temp_dir(job_id: str) -> str:
    path = os.path.join(settings.temp_dir, job_id)
    os.makedirs(path, exist_ok=True)
    return path


def _cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def cleanup_job_dir(job_id: str) -> None:
    _cleanup_dir(os.path.join(settings.temp_dir, job_id))


async def save_upload(job_id: str, upload: UploadFile) -> SavedUpload:
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in settings.allowed_extensions:
        raise VideoValidationError(
            f"Unsupported file type '{ext or 'unknown'}'. Only .mp4 and .mov are accepted."
        )

    job_dir = _job_temp_dir(job_id)
    dest_path = os.path.join(job_dir, f"upload{ext}")
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    chunk_size = 1024 * 1024

    total = 0
    try:
        with open(dest_path, "wb") as out_file:
            while chunk := await upload.read(chunk_size):
                total += len(chunk)
                if total > max_bytes:
                    raise VideoValidationError(
                        f"File exceeds the {settings.max_file_size_mb}MB size limit."
                    )
                out_file.write(chunk)
    except VideoValidationError:
        _cleanup_dir(job_dir)
        raise
    finally:
        await upload.close()

    if total == 0:
        _cleanup_dir(job_dir)
        raise VideoValidationError("Uploaded file is empty.")

    return SavedUpload(path=dest_path, job_dir=job_dir)


async def probe_duration_seconds(path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0 or not stdout.strip():
        raise VideoValidationError(
            "Could not read video file. It may be corrupted or in an unsupported format."
        )
    try:
        return float(stdout.strip())
    except ValueError as exc:
        raise VideoValidationError("Could not determine video duration.") from exc


async def enforce_duration_cap(job_id: str, path: str) -> None:
    try:
        duration = await probe_duration_seconds(path)
    except VideoValidationError:
        cleanup_job_dir(job_id)
        raise
    if duration > settings.max_duration_seconds:
        cleanup_job_dir(job_id)
        raise VideoValidationError(
            f"Video is {duration:.0f}s long, which exceeds the "
            f"{settings.max_duration_seconds}s limit."
        )


async def normalize_video(src_path: str, job_dir: str) -> str:
    normalized_path = os.path.join(job_dir, "normalized.mp4")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i", src_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-movflags", "+faststart",
        normalized_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise VideoValidationError(
            "Failed to process video file: " + stderr.decode(errors="ignore")[-500:]
        )
    return normalized_path
