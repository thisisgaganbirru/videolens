import logging
import os

from ..domain.entities import RunStatus
from ..domain.errors import GeminiConfigurationError, MediaValidationError
from ..domain.ports import AnalysisEngine, MediaProcessor, ObjectStore, RunRepository

logger = logging.getLogger("videolens")


class ProcessRunUseCase:
    """Runs the full analysis pipeline for one run: fetch/validate the
    source media, normalize it, analyze it with Gemini, and persist the
    result. Invoked both by the in-process local runner and the arq worker."""

    def __init__(
        self,
        *,
        runs: RunRepository,
        media: MediaProcessor,
        storage: ObjectStore,
        analysis: AnalysisEngine,
    ) -> None:
        self._runs = runs
        self._media = media
        self._storage = storage
        self._analysis = analysis

    async def execute(
        self,
        run_id: str,
        saved_path: str | None = None,
        run_dir: str | None = None,
        source_url: str | None = None,
        source_key: str | None = None,
        gemini_api_key: str | None = None,
    ) -> None:
        await self._runs.set_status(run_id, RunStatus.PROCESSING)
        metadata = None
        try:
            if source_key:
                run_dir = self._media.create_run_dir(run_id)
                extension = os.path.splitext(source_key)[1].lower()
                saved_path = os.path.join(run_dir, f"source{extension}")
                await self._storage.download_source(source_key, saved_path)
                await self._media.enforce_duration_cap(run_id, saved_path)
            elif source_url:
                await self._runs.set_stage(run_id, "downloading")
                downloaded = await self._media.download_url(run_id, source_url)
                saved_path = downloaded.path
                run_dir = downloaded.run_dir
                if downloaded.metadata is not None:
                    metadata = downloaded.metadata
                    await self._runs.set_source_metadata(run_id, metadata)
                await self._media.enforce_duration_cap(run_id, saved_path)

            if not saved_path or not run_dir:
                raise MediaValidationError("No media source was provided.")

            await self._runs.set_stage(run_id, "normalizing")
            normalized_path = await self._media.normalize_media(saved_path, run_dir)

            async def on_stage(stage: str) -> None:
                await self._runs.set_stage(run_id, stage)

            # The publisher's own title/caption/stats are context the pixels do
            # not carry - names, jargon, and spellings the audio only says out
            # loud. Only URL runs have it; uploads pass None and the engine
            # falls back to analyzing the media alone.
            result = await self._analysis.analyze_with_retry(
                normalized_path,
                on_stage=on_stage,
                api_key=gemini_api_key,
                metadata=metadata,
            )
            await self._runs.set_result(run_id, result)
        except MediaValidationError as exc:
            await self._runs.set_error(run_id, str(exc))
        except GeminiConfigurationError as exc:
            await self._runs.set_error(run_id, str(exc))
        except Exception:
            logger.exception("Run %s failed", run_id)
            await self._runs.set_error(run_id, "Media analysis failed. Please try again.")
        finally:
            if source_key:
                try:
                    await self._storage.delete_source(source_key)
                except Exception:
                    logger.exception("Could not delete source object for run %s", run_id)
            self._media.cleanup_run_dir(run_id)
