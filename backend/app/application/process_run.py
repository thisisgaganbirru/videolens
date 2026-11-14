import asyncio
import logging
import os

from ..domain.entities import AnalysisCompleteness, MediaVisuals, RunStatus
from ..domain.entitlements import MediaLimits, MediaTier
from ..domain.errors import (  # the two messages are re-exported for callers and tests
    BYOK_KEY_EXPIRED_MESSAGE,
    RUN_INTERRUPTED_MESSAGE,
    AnalysisUnavailableError,
    GeminiConfigurationError,
    LongRunInProgressError,
    MediaValidationError,
    OwnKeyUnavailableError,
    UserFacingError,
)
from ..domain.ports import (
    AccountFreeRunAllowance,
    AnalysisEngine,
    FreeRunAllowance,
    LongRunGuard,
    MediaProcessor,
    ObjectStore,
    RunRepository,
)
from .billing import ExtraRunBilling
from .entitlements import EntitlementResolver
from .free_run_holds import settle_free_run_holds

logger = logging.getLogger("videolens")

# A run in either state has ended. The store never writes to it again, and
# the worker never starts or continues work for it.
_ENDED = (RunStatus.COMPLETE, RunStatus.FAILED)


class _RunEndedElsewhere(Exception):
    """Raised at a checkpoint when the run is no longer this worker's to
    finish: the read-time stale-run check already failed it (it waited or
    ran past its job timeout), or its record is gone. Internal to this
    module; `execute` stops quietly and cleans up."""

    def __init__(self, status: RunStatus | None) -> None:
        super().__init__(status.value if status is not None else "missing")
        # The person was told it failed and got nothing back, so a free run
        # it still holds is handed back. A recordless run is not refunded
        # (its hold expires on its own), as before.
        self.refund = status is RunStatus.FAILED


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
        free_runs: FreeRunAllowance,
        account_free_runs: AccountFreeRunAllowance | None = None,
        entitlements: EntitlementResolver | None = None,
        long_runs: LongRunGuard | None = None,
        extra_runs: ExtraRunBilling | None = None,
    ) -> None:
        self._runs = runs
        self._media = media
        self._storage = storage
        self._analysis = analysis
        self._free_runs = free_runs
        self._account_free_runs = account_free_runs
        # Both None (tests, older wiring) = no long-run guard in the worker.
        self._entitlements = entitlements
        self._long_runs = long_runs
        # None (tests, older wiring) = nothing is ever billed per run.
        self._extra_runs = extra_runs

    async def _bill_extra_run(self, run_id: str) -> None:
        """The run's result is stored: if it was a paid account's extra run,
        it is billed now, once. Never raises."""
        if self._extra_runs is not None:
            await self._extra_runs.complete(run_id)

    async def _void_extra_run(self, run_id: str) -> None:
        """However the run ended, a held extra run that did not complete is
        never billed. A no-op after `_bill_extra_run` (already due)."""
        if self._extra_runs is not None:
            await self._extra_runs.void(run_id)

    async def _analyze_captions(
        self, run_id: str, source_url: str, gemini_api_key: str | None, limits: MediaLimits | None = None
    ) -> bool:
        """Salvage a failed download via the subtitle track.

        Returns True when the run was completed from captions. Any failure
        here returns False so the caller re-raises the *original* download
        error - the caption attempt is a bonus, and its own problems must not
        replace the diagnosis of why the download failed.
        """
        visuals: asyncio.Task[MediaVisuals] | None = None
        try:
            # The run's own duration limit: a caption track must not become a
            # way around it, nor be held to a smaller one than the run's.
            captions = await self._media.fetch_captions(source_url, limits)
            if captions is None:
                return False
            # Checkpoint before the caption path's Gemini call.
            await self._ensure_not_ended(run_id)
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
            if not await self._runs.set_result(run_id, result, AnalysisCompleteness.CAPTIONS_ONLY):
                raise await self._ended_elsewhere(run_id)
            await self._bill_extra_run(run_id)
            logger.info("Run %s recovered from captions after the download failed", run_id)
            return True
        except (GeminiConfigurationError, AnalysisUnavailableError, _RunEndedElsewhere):
            # A run that ended elsewhere stops here, not with the download
            # error. Neither of the other two is the caption path's fault, and both have honest advice
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

    async def _settle_free_run(
        self, run_id: str, *, refund: bool, reason: str = "was rejected before analysis"
    ) -> None:
        """Hand the run's free run back (`refund`) or just forget it. Runs
        that took none (own key, allowance off) hold nothing, so this is a
        no-op for them; only the first release of a run acts."""
        await settle_free_run_holds(
            run_id,
            refund=refund,
            free_runs=self._free_runs,
            account_free_runs=self._account_free_runs,
            reason=reason,
        )

    async def _ended_elsewhere(self, run_id: str) -> "_RunEndedElsewhere":
        run = await self._runs.get(run_id)
        return _RunEndedElsewhere(run.status if run is not None else None)

    async def _ensure_not_ended(self, run_id: str) -> None:
        """A checkpoint before costly work (FFmpeg, Gemini): one read of the
        run. Raises `_RunEndedElsewhere` when the stale-run check failed the
        run while this worker was busy, or the record is gone."""
        run = await self._runs.get(run_id)
        if run is None or run.status in _ENDED:
            raise _RunEndedElsewhere(run.status if run is not None else None)

    async def _claim_long_run(
        self, run_id: str, limits: MediaLimits | None, duration: float | None, size_bytes: int | None
    ) -> None:
        if limits is None or not limits.long_run_key or self._entitlements is None or self._long_runs is None:
            return
        if not self._entitlements.is_long(duration_seconds=duration, size_bytes=size_bytes):
            return
        if not await self._long_runs.try_acquire(limits.long_run_key, run_id):
            self._media.cleanup_run_dir(run_id)
            raise LongRunInProgressError()

    async def _release_long_run(self, run_id: str, limits: MediaLimits | None) -> None:
        # Released however the run ended; a no-op for a run that never held
        # the slot. Bookkeeping only: the slot expires on its own.
        if limits is None or not limits.long_run_key or self._long_runs is None:
            return
        try:
            await self._long_runs.release(limits.long_run_key, run_id)
        except Exception:
            logger.exception("Could not release the long-run slot for run %s", run_id)

    async def _drop_before_start(
        self, run_id: str, gemini_api_key: str | None, limits: MediaLimits | None, source_key: str | None
    ) -> bool:
        """Whether the job must stop before any work. One read of the run.

        - Record gone (RUN_TTL_SECONDS, or the account was deleted): nothing
          could show its result. Not refunded; its hold expires on its own.
        - Already ended: the read-time stale-run check failed it while the
          job waited in the queue (past its job timeout), or this is a retry
          of a job that already finished. Its outcome stands. A free run it
          still holds is handed back when it is `failed`: the person got
          nothing. A run that finished in a worker already released its
          hold, so that release is a no-op.
        - Admitted on the caller's own key but no key arrived: it skipped the
          free-run and daily cap checks at intake (and, signed in, got the
          bigger limits). Its key lives only in the single-use vault, so no
          key means the entry expired while the job waited (15 min), or an
          earlier attempt already took it (an arq retry after a worker
          restart). Running it would spend the shared key on a run that was
          never counted, so it fails instead.

        Every stop cleans up what intake left (the S3 source, the run
        directory) and releases a long-run slot this run holds. `execute`
        returns straight after, so its finally never settles, releases or
        deletes the same run a second time. Returns False, having done
        nothing, for a run that should go ahead.
        """
        run = await self._runs.get(run_id)
        refund = False
        if run is None:
            logger.error("Run %s has no record left, so it was not started", run_id)
        elif run.status in _ENDED:
            logger.warning(
                "Run %s reached the worker after it ended (%s); dropped without any work",
                run_id,
                run.status.value,
            )
            refund = run.status is RunStatus.FAILED
        elif not gemini_api_key and (
            (limits is not None and limits.tier is MediaTier.SIGNED_IN_BYOK) or run.admitted_byok
        ):
            # Still queued: the key expired before any worker took the job.
            # Processing: an earlier attempt started it, then its worker died.
            # An own-key run took no free run, so settling below is a no-op.
            exc = OwnKeyUnavailableError(started=run.status is RunStatus.PROCESSING)
            self._log_failure(run_id, exc)
            await self._runs.set_error(run_id, str(exc))
        else:
            return False
        await self._settle_free_run(run_id, refund=refund, reason="had already been marked failed")
        await self._void_extra_run(run_id)
        await self._release_long_run(run_id, limits)
        self._media.cleanup_run_dir(run_id)
        if source_key:
            try:
                await self._storage.delete_source(source_key)
            except Exception:
                logger.exception("Could not delete source object for run %s", run_id)
        return True

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
        limits: MediaLimits | None = None,
    ) -> None:
        # `limits` are the ones the API admitted the run under (None: a job
        # enqueued before they travelled with it, so the standard ones).
        # The first checkpoint, before any download: a run that already
        # ended, has no record, or lost its own key does no work at all.
        if await self._drop_before_start(run_id, gemini_api_key, limits, source_key):
            return
        await self._runs.set_status(run_id, RunStatus.PROCESSING)
        metadata = None
        visuals: asyncio.Task[MediaVisuals] | None = None
        # True only when a link run is turned away before any analysis: the
        # link could not be fetched, or it was fetched and then failed the
        # duration cap. Nothing reached Gemini, so a free run it took is
        # handed back (intake already does the same for over-long uploads).
        # A caption fallback that got as far as Gemini and failed there does
        # not count (that is a Gemini failure), and neither does normalize or
        # analyze. The cap is never checked on the caption path, so a run the
        # captions handled can never set this.
        rejected_before_analysis = False
        # True when a checkpoint finds the stale-run check already failed the
        # run: the person got nothing, so a free run it holds goes back.
        refund_ended_elsewhere = False
        try:
            if source_url and not source_key:
                await self._runs.set_stage(run_id, "downloading")
                try:
                    downloaded = await self._media.download_url(run_id, source_url, limits)
                except MediaValidationError as exc:
                    # Every download route failed. Captions are served by a
                    # different pipeline on these platforms, so they are often
                    # still reachable when the media bytes are not - a real
                    # transcript beats "please try again".
                    if await self._analyze_captions(run_id, source_url, gemini_api_key, limits):
                        return
                    rejected_before_analysis = True
                    raise exc
                except Exception:
                    rejected_before_analysis = True
                    raise
                saved_path = downloaded.path
                run_dir = downloaded.run_dir
                if downloaded.metadata is not None:
                    metadata = downloaded.metadata
                    await self._runs.set_source_metadata(run_id, metadata)
                try:
                    duration = await self._media.enforce_duration_cap(run_id, saved_path, limits)
                    # A link's length is only known now: claim the account's
                    # one long-run slot if it is above the standard limits.
                    await self._claim_long_run(run_id, limits, duration, downloaded.size_bytes)
                except Exception:
                    # Too long (or unreadable) once fetched: still before any
                    # Gemini call. Cancellation is a BaseException, so it is
                    # not caught here and is not a rejection.
                    rejected_before_analysis = True
                    raise
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
                duration = await self._media.enforce_duration_cap(run_id, saved_path, limits)
                # Intake already holds the slot for a long upload; this
                # re-arms its expiry now the worker has started on it.
                await self._claim_long_run(run_id, limits, duration, None)
                await self._record_duration(run_id, duration)
                visuals = self._start_visuals(media_path=saved_path, duration_seconds=duration)

            if not saved_path or not run_dir:
                raise MediaValidationError("No media source was provided.")

            if visuals is None:
                # Local-mode upload: probed at intake, so no duration here and
                # the frame grab uses its ~1s default.
                visuals = self._start_visuals(media_path=saved_path)

            # Checkpoints before the two costly steps: a long download or
            # re-encode can outlast the stale-run threshold.
            await self._ensure_not_ended(run_id)
            await self._runs.set_stage(run_id, "normalizing")
            normalized_path = await self._media.normalize_media(saved_path, run_dir)

            async def on_stage(stage: str) -> None:
                await self._runs.set_stage(run_id, stage)

            # The publisher's own title/caption/stats are context the pixels do
            # not carry - names, jargon, and spellings the audio only says out
            # loud. Only URL runs have it; uploads pass None and the engine
            # falls back to analyzing the media alone.
            await self._ensure_not_ended(run_id)
            result = await self._analysis.analyze_with_retry(
                normalized_path,
                on_stage=on_stage,
                api_key=gemini_api_key,
                metadata=metadata,
            )
            await self._record_visuals(run_id, visuals)
            if not await self._runs.set_result(run_id, result):
                # The stale-run check failed it while Gemini was working. The
                # client was already told it failed and stopped polling, so
                # the failure stands and the result is dropped.
                raise await self._ended_elsewhere(run_id)
            await self._bill_extra_run(run_id)
        except _RunEndedElsewhere as exc:
            logger.warning(
                "Run %s ended elsewhere (%s) while this worker had it; stopped and cleaned up", run_id, exc
            )
            refund_ended_elsewhere = exc.refund
        except (
            MediaValidationError,
            AnalysisUnavailableError,
            GeminiConfigurationError,
            LongRunInProgressError,
        ) as exc:
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
            await self._settle_free_run(run_id, refund=rejected_before_analysis or refund_ended_elsewhere)
            await self._void_extra_run(run_id)
            await self._release_long_run(run_id, limits)
            if source_key:
                try:
                    await self._storage.delete_source(source_key)
                except Exception:
                    logger.exception("Could not delete source object for run %s", run_id)
            self._media.cleanup_run_dir(run_id)
