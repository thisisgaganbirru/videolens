import asyncio
import logging
import os

from ..domain.entities import AnalysisCompleteness, RunStatus, TokenUsage
from ..domain.entitlements import media_resolution_for
from ..domain.errors import (
    AnalysisUnavailableError,
    GeminiConfigurationError,
    MediaValidationError,
    UserFacingError,
)
from ..domain.ports import AnalysisEngine, MediaProcessor, ObjectStore, RunRepository
from .record_usage import RecordUsageUseCase

logger = logging.getLogger("videolens")

RUN_INTERRUPTED_MESSAGE = (
    "Analysis was interrupted before it finished. Please try again."
)


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
        usage: RecordUsageUseCase | None = None,
    ) -> None:
        self._runs = runs
        self._media = media
        self._storage = storage
        self._analysis = analysis
        self._usage = usage

    async def _analyze_captions(
        self, run_id: str, source_url: str, gemini_api_key: str | None
    ) -> bool:
        """Salvage a failed download via the subtitle track.

        Returns True when the run was completed from captions. Any failure
        here returns False so the caller re-raises the *original* download
        error - the caption attempt is a bonus, and its own problems must not
        replace the diagnosis of why the download failed.
        """
        try:
            captions = await self._media.fetch_captions(source_url)
            if captions is None:
                return False
            await self._runs.set_stage(run_id, "analyzing_captions")
            result = await self._analysis.analyze_captions(captions, api_key=gemini_api_key)
            if captions.metadata is not None:
                await self._runs.set_source_metadata(run_id, captions.metadata)
            await self._runs.set_result(run_id, result, AnalysisCompleteness.CAPTIONS_ONLY)
            logger.info("Run %s recovered from captions after the download failed", run_id)
            return True
        except (GeminiConfigurationError, AnalysisUnavailableError):
            # Neither is the caption path's fault, and both have honest advice
            # of their own ("unavailable", "try again shortly") that beats
            # re-reporting why the download failed.
            raise
        except Exception:
            logger.exception("Caption fallback failed for run %s", run_id)
            return False

    @staticmethod
    def _log_failure(run_id: str, exc: UserFacingError) -> None:
        if exc.log_detail:
            logger.error("Run %s failed: %s | %s", run_id, exc, exc.log_detail)
        else:
            logger.error("Run %s failed: %s", run_id, exc)

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
        # The run carries the cap it was admitted under and the workspace to
        # bill; both were decided at intake so the worker needs no plan
        # lookup. A run that vanished from the store (TTL, flushed Redis)
        # still gets the deployment defaults rather than a crash.
        run = await self._runs.get(run_id)
        max_seconds = run.max_duration_seconds if run else None
        workspace_id = run.workspace_id if run else None
        duration = run.duration_seconds if run else None
        metadata = None
        tokens: TokenUsage | None = None
        try:
            if source_url and not source_key:
                await self._runs.set_stage(run_id, "downloading")
                try:
                    downloaded = await self._media.download_url(run_id, source_url)
                except MediaValidationError as exc:
                    # Every download route failed. Captions are served by a
                    # different pipeline on these platforms, so they are often
                    # still reachable when the media bytes are not - a real
                    # transcript beats "please try again".
                    if await self._analyze_captions(run_id, source_url, gemini_api_key):
                        return
                    raise exc
                saved_path = downloaded.path
                run_dir = downloaded.run_dir
                if downloaded.metadata is not None:
                    metadata = downloaded.metadata
                    await self._runs.set_source_metadata(run_id, metadata)
                duration = await self._media.enforce_duration_cap(run_id, saved_path, max_seconds)
                await self._runs.set_duration(run_id, duration)
            elif source_key:
                run_dir = self._media.create_run_dir(run_id)
                extension = os.path.splitext(source_key)[1].lower()
                saved_path = os.path.join(run_dir, f"source{extension}")
                await self._storage.download_source(source_key, saved_path)
                duration = await self._media.enforce_duration_cap(run_id, saved_path, max_seconds)
                await self._runs.set_duration(run_id, duration)

            if not saved_path or not run_dir:
                raise MediaValidationError("No media source was provided.")

            await self._runs.set_stage(run_id, "normalizing")
            normalized_path = await self._media.normalize_media(saved_path, run_dir)

            async def on_stage(stage: str) -> None:
                await self._runs.set_stage(run_id, stage)

            async def on_usage(usage: TokenUsage) -> None:
                nonlocal tokens
                tokens = usage
                await self._runs.set_usage(run_id, usage)

            # Long media is read at low resolution: it is what keeps an hour of
            # video inside the model's context, and a third of the cost.
            resolution = media_resolution_for(duration)

            # The publisher's own title/caption/stats are context the pixels do
            # not carry - names, jargon, and spellings the audio only says out
            # loud. Only URL runs have it; uploads pass None and the engine
            # falls back to analyzing the media alone.
            result = await self._analysis.analyze_with_retry(
                normalized_path,
                on_stage=on_stage,
                api_key=gemini_api_key,
                metadata=metadata,
                resolution=resolution,
                on_usage=on_usage,
            )
            await self._runs.set_result(run_id, result)

            # Metered after the result is safely stored: a person who paid for
            # minutes gets their notes even if the ledger write fails, and a
            # caller on their own Gemini key is never charged for our model.
            if self._usage is not None and workspace_id and duration and not gemini_api_key:
                try:
                    await self._usage.execute(
                        run_id=run_id,
                        workspace_id=workspace_id,
                        duration_seconds=duration,
                        resolution=resolution,
                        tokens=tokens,
                    )
                except Exception:  # noqa: BLE001 - the run already succeeded
                    logger.exception("Usage for run %s could not be recorded", run_id)
        except (MediaValidationError, AnalysisUnavailableError, GeminiConfigurationError) as exc:
            # The message is written for the person on the screen; anything an
            # operator would need is on `log_detail` and stops here. Storing it
            # would put it straight back on the phone, which is the whole thing
            # this split exists to prevent.
            self._log_failure(run_id, exc)
            await self._runs.set_error(run_id, str(exc))
        except asyncio.CancelledError:
            # arq cancels the coroutine when `job_timeout` expires, and
            # CancelledError is a BaseException - so the catch-all below never
            # sees it. Without this the run sits in PROCESSING until its TTL
            # expires, days later, with nothing to explain it. Best-effort:
            # the write may not land if the loop is already tearing down,
            # which is what the read-time staleness check backstops.
            try:
                await self._runs.set_error(run_id, RUN_INTERRUPTED_MESSAGE)
            except BaseException:  # noqa: BLE001 - never mask the cancellation
                pass
            raise
        except Exception:
            logger.exception("Run %s failed", run_id)
            await self._runs.set_error(run_id, "The analysis didn't finish. Please try again.")
        finally:
            if source_key:
                try:
                    await self._storage.delete_source(source_key)
                except Exception:
                    logger.exception("Could not delete source object for run %s", run_id)
            self._media.cleanup_run_dir(run_id)
