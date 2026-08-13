import os
import shutil

from ...domain.entities import SavedUpload
from ...domain.errors import MediaValidationError
from ...domain.ports import UploadedFile
from ..config import Settings


def create_run_dir(settings: Settings, run_id: str) -> str:
    path = os.path.join(settings.temp_dir, run_id)
    os.makedirs(path, exist_ok=True)
    return path


def _cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def cleanup_run_dir(settings: Settings, run_id: str) -> None:
    _cleanup_dir(os.path.join(settings.temp_dir, run_id))


async def save_upload(settings: Settings, run_id: str, upload: UploadedFile) -> SavedUpload:
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in settings.allowed_extensions:
        raise MediaValidationError(
            f"Unsupported file type '{ext or 'unknown'}'. Only .mp3, .mp4, and .mov are accepted."
        )

    run_dir = create_run_dir(settings, run_id)
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
