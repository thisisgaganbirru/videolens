import logging

from . import video
from .gemini_client import analyze_video_with_retry
from .jobs import job_store
from .models import JobStatus
from .video import VideoValidationError

logger = logging.getLogger("videolens")


async def run_job(job_id: str, saved_path: str, job_dir: str) -> None:
    await job_store.set_status(job_id, JobStatus.PROCESSING)
    try:
        normalized_path = await video.normalize_video(saved_path, job_dir)
        result = await analyze_video_with_retry(normalized_path)
        await job_store.set_result(job_id, result)
    except VideoValidationError as exc:
        await job_store.set_error(job_id, str(exc))
    except Exception:
        logger.exception("Job %s failed", job_id)
        await job_store.set_error(job_id, "Video analysis failed. Please try again.")
    finally:
        video.cleanup_job_dir(job_id)
