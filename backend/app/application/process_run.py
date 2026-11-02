import asyncio
import logging
import os

from ..domain.entities import AnalysisCompleteness, MediaVisuals, RunStatus
from ..domain.errors import (
    AnalysisUnavailableError,
    GeminiConfigurationError,
    MediaValidationError,
    UserFacingError,
)
from ..domain.ports import AnalysisEngine, MediaProcessor, ObjectStore, RunRepository

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
    ) -> None:
        self._runs = runs
        self._media = media
        self._storage = storage
        self._analysis = analysis

    async def _analyze_captions(
        self, run_id: str, source_url: str, gemini_api_key: str | None
    ) -> bool:
        """Salvage a failed download via the subtitle track.

        Returns True when the run was completed from captions. Any failure
        here returns False so the caller re-raises the *original* download
        error - the caption attempt is a bonus, and its own problems must not
        replace the diagnosis of why the download failed.
        """
        visuals: asyncio.Task[MediaVisuals] | None = None
        try:
            captions = await self._media.fetch_captions(source_url)
            if captions is None:
                return False
            await self._runs.set_stage(run_id, "analyzing_captions")
            # No media on this path: the poster can only be yt-dlp's own.
            visuals = self._start_visuals(
                thumbnail_urls=captions.thumbnail_urls,
                width=captions.width,
                height=captions.height,
            )
            result = await self._analysis.analyze_captions(captions, api_key=gemini_api_key)
            if captions.metadata is not None:
                await self._runs.set_source_metadata(run_id, captions.metadata)
            await self._record_duration(run_id, captions.duration_seconds)
            await self._record_visuals(run_id, visuals)
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
        finally:
            await self._discard_visuals(visuals)

    async def _record_duration(self, run_id: str, duration: float | None) -> None:
        # Shown on the history card. Purely cosmetic, so a failed write must
        # not fail an otherwise healthy run.
        if duration is None:
            return
        try:
            await self._runs.set_duration(run_id, duration)
        except Exception:
            logger.exception("Could not record duration for run %s", run_id)

    def _start_visuals(self, **kwargs) -> "asyncio.Task[MediaVisuals]":
        """Capture the history poster and display size alongside the analysis
        rather than ahead of it: it is a second or two of HTTP and FFmpeg work
        that nothing else has to wait for."""
        return asyncio.create_task(self._media.describe_visuals(**kwargs))

    async def _record_visuals(
        self, run_id: str, task: "asyncio.Task[MediaVisuals] | None"
    ) -> None:
        # Written *before* the run is marked complete, so the poll that first
        # sees `complete` already carries what the browser files into History.
        # Cosmetic: no failure here may fail the run.
        if task is None:
            return
        try:
            visuals = await task
            if visuals.thumbnail is None and visuals.width is None:
                return
            await self._runs.set_visuals(run_id, visuals)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not record visuals for run %s", run_id)

    @staticmethod
    async def _discard_visuals(task: "asyncio.Task[MediaVisuals] | None") -> None:
        """Stop an unfinished capture before the run directory it reads from
        is deleted (the failure and cancellation paths)."""
        if task is None:
            return
        if task.done():
            if not task.cancelled():
                task.exception()  # mark retrieved so asyncio does not warn
            return
        task.cancel()
        try:
            await task
        except BaseException:  # noqa: BLE001 - cancelled on purpose
            pass

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
        metadata = None
        visuals: asyncio.Task[MediaVisuals] | None = None
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
                duration = await self._media.enforce_duration_cap(run_id, saved_path)
                await self._record_duration(run_id, duration)
                visuals = self._start_visuals(
                    media_path=saved_path,
                    thumbnail_urls=downloaded.thumbnail_urls,
                    width=downloaded.width,
                    height=downloaded.height,
                    duration_seconds=duration,
                )
            elif source_key:
                run_dir = self._media.create_run_dir(run_id)
                extension = os.path.splitext(source_key)[1].lower()
                saved_path = os.path.join(run_dir, f"source{extension}")
                await self._storage.download_source(source_key, saved_path)
                duration = await self._media.enforce_duration_cap(run_id, saved_path)
                await self._record_duration(run_id, duration)
                visuals = self._start_visuals(media_path=saved_path, duration_seconds=duration)

            if not saved_path or not run_dir:
                raise MediaValidationError("No media source was provided.")

            if visuals is None:
                # Local-mode upload: probed at intake, so no duration here and
                # the frame grab uses its ~1s default.
                visuals = self._start_visuals(media_path=saved_path)

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
            await self._record_visuals(run_id, visuals)
            await self._runs.set_result(run_id, result)
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
            await self._discard_visuals(visuals)
            if source_key:
                try:
                    await self._storage.delete_source(source_key)
                except Exception:
                    logger.exception("Could not delete source object for run %s", run_id)
            self._media.cleanup_run_dir(run_id)
