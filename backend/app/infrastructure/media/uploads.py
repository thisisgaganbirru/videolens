import os
import shutil

from ...domain.entities import SavedUpload
from ...domain.errors import MediaValidationError
from ...domain.ports import UploadedFile
from ..config import Settings


def validate_temp_dir(settings: Settings) -> None:
    """Fail at startup on a `TEMP_DIR` this container cannot actually use.

    A Windows path (`C:/Users/.../Temp/videolens`, typically copied from a
    local `.env` into a deployment's variables) is the case this exists for,
    and it is invisible without an explicit check: `C:` is a perfectly legal
    directory name on Linux, so `os.makedirs` *succeeds*, silently creating a
    relative directory next to the process instead of the intended absolute
    one. The app then boots reporting itself healthy and downloads land in
    that junk directory without complaint.

    FFmpeg is the first component strict enough to object, because it parses
    everything before the first colon of an output filename as a protocol
    scheme: it sees `C`, finds no such protocol, and fails the run with
    `Protocol not found` - at the normalize step, far from the cause, and
    only for runs that get that far. Checking here turns a confusing
    mid-pipeline media error into a loud startup failure naming the variable.
    """
    temp_dir = settings.temp_dir

    if not os.path.isabs(temp_dir):
        raise RuntimeError(
            f"TEMP_DIR must be an absolute POSIX path, got {temp_dir!r}. "
            "A Windows path carried over from a local .env is the usual cause; "
            "this container expects something like /tmp/videolens."
        )

    try:
        os.makedirs(temp_dir, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"TEMP_DIR {temp_dir!r} could not be created: {exc}") from exc

    if not os.access(temp_dir, os.W_OK):
        raise RuntimeError(
            f"TEMP_DIR {temp_dir!r} exists but is not writable by this process. "
            "The image creates and chowns /tmp/videolens for the non-root user it runs as, "
            "so a different path has to be made writable deliberately."
        )


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
            f"Only .mp3, .mp4 and .mov files are supported - this one is "
            f"{ext or 'an unknown type'}."
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
                        f"That file is over the {settings.max_file_size_mb}MB limit."
                    )
                out_file.write(chunk)
    except MediaValidationError:
        _cleanup_dir(run_dir)
        raise
    finally:
        await upload.close()

    if total == 0:
        _cleanup_dir(run_dir)
        raise MediaValidationError("That file is empty.")

    return SavedUpload(path=dest_path, run_dir=run_dir)
