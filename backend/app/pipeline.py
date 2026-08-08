import logging
import os

from . import video
from .gemini_client import GeminiConfigurationError, analyze_video_with_retry
from .models import RunStatus
from .runs import run_store
from .storage import delete_source, download_source
from .video import MediaValidationError

logger = logging.getLogger("videolens")


async def run_pipeline(
    run_id: str,
    saved_path: str | None = None,
    run_dir: str | None = None,
    source_url: str | None = None,
    source_key: str | None = None,
    gemini_api_key: str | None = None,
) -> None:
    await run_store.set_status(run_id, RunStatus.PROCESSING)
    try:
        if source_key:
            run_dir = video.create_run_dir(run_id)
            extension = os.path.splitext(source_key)[1].lower()
            saved_path = os.path.join(run_dir, f"source{extension}")
            await download_source(source_key, saved_path)
            await video.enforce_duration_cap(run_id, saved_path)
        elif source_url:
            await run_store.set_stage(run_id, "downloading")
            downloaded = await video.download_url(run_id, source_url)
            saved_path = downloaded.path
            run_dir = downloaded.run_dir
            await video.enforce_duration_cap(run_id, saved_path)

        if not saved_path or not run_dir:
            raise MediaValidationError("No media source was provided.")

        await run_store.set_stage(run_id, "normalizing")
        normalized_path = await video.normalize_media(saved_path, run_dir)

        async def on_stage(stage: str) -> None:
            await run_store.set_stage(run_id, stage)

        result = await analyze_video_with_retry(normalized_path, on_stage=on_stage, api_key=gemini_api_key)
        await run_store.set_result(run_id, result)
    except MediaValidationError as exc:
        await run_store.set_error(run_id, str(exc))
    except GeminiConfigurationError as exc:
        await run_store.set_error(run_id, str(exc))
    except Exception:
        logger.exception("Run %s failed", run_id)
        await run_store.set_error(run_id, "Media analysis failed. Please try again.")
    finally:
        if source_key:
            try:
                await delete_source(source_key)
            except Exception:
                logger.exception("Could not delete source object for run %s", run_id)
        video.cleanup_run_dir(run_id)
