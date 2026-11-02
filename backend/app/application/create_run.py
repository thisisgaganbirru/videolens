import os
import uuid
from datetime import datetime, timezone

from ..domain.entities import FreeRunClaim, Principal, Run
from ..domain.errors import (
    DeviceTokenInvalidError,
    FreeRunsExhaustedError,
    InvalidSourceError,
    MediaValidationError,
    QuotaExceededError,
    RunSchedulingError,
    TermsNotAcceptedError,
)
from ..domain.policies import seconds_until_next_utc_day
from ..domain.run_facts import file_platform
from ..domain.ports import (
    DeviceTokenSigner,
    FreeRunAllowance,
    JobQueue,
    MediaProcessor,
    ObjectStore,
    RunRepository,
    SpendCap,
    UploadedFile,
)

FREE_RUNS_USED_MESSAGE = "You have used your free runs. Add your own Gemini key to keep going."



class CreateRunUseCase:
    """Accepts a media source (file or URL), applies the intake business
    rules (terms accepted, exactly one source, free-run allowance, daily
    spend cap), and schedules the run for analysis.

    `distributed` mirrors the deployment topology (Redis queue + S3 present):
    in that mode an uploaded file is pushed to object storage and the local
    copy is deleted immediately, since the worker that processes it runs in
    a different process than the one that received the upload.
    """

    def __init__(
        self,
        *,
        runs: RunRepository,
        media: MediaProcessor,
        storage: ObjectStore,
        queue: JobQueue,
        spend_cap: SpendCap,
        free_runs: FreeRunAllowance,
        device_tokens: DeviceTokenSigner,
        distributed: bool,
    ) -> None:
        self._runs = runs
        self._media = media
        self._storage = storage
        self._queue = queue
        self._spend_cap = spend_cap
        self._free_runs = free_runs
        self._device_tokens = device_tokens
        self._distributed = distributed

    async def execute(
        self,
        *,
        principal: Principal,
        accept_terms: bool,
        file: UploadedFile | None,
        url: str | None,
        gemini_api_key: str | None,
        device_token: str | None = None,
        client_ip: str = "",
    ) -> Run:
        if not accept_terms:
            raise TermsNotAcceptedError("Accept the media-use terms before analysis.")

        run_id = str(uuid.uuid4())
        source_url = url.strip() if url else None
        if (file is None) == (source_url is None):
            if file is not None:
                await file.close()
            raise InvalidSourceError("Provide exactly one source: either a media file or a public URL.")

        # Nothing below this line may run for a caller who isn't allowed to
        # start one: no download, no FFmpeg, no budget spent.
        claim = await self._admit(
            principal=principal,
            gemini_api_key=gemini_api_key,
            device_token=device_token,
            client_ip=client_ip,
        )
        try:
            if claim is not None:
                # Held before the job is enqueued, so the pipeline can find it
                # however quickly the download fails: a link that cannot be
                # fetched hands the free run back (ProcessRunUseCase).
                await self._free_runs.hold(run_id, claim)
            return await self._accept(
                run_id=run_id,
                principal=principal,
                file=file,
                source_url=source_url,
                gemini_api_key=gemini_api_key,
            )
        except Exception:
            # A rejected intake (over the daily cap, too long, unschedulable)
            # must not cost the caller one of their free runs. Drop the hold
            # first so nothing later can hand the same run back a second time.
            if claim is not None:
                await self._free_runs.release(run_id, refund=False)
                await self._free_runs.refund(claim)
            raise

    async def _admit(
        self,
        *,
        principal: Principal,
        gemini_api_key: str | None,
        device_token: str | None,
        client_ip: str,
    ) -> FreeRunClaim | None:
        """Whether this caller may start a run on the shared Gemini key.

        The one seam a signed-in plan check slots into later: today the only
        answer is "own key: always" or "anonymous: within today's free runs".
        Returns the free run taken, so it can be handed back if the intake
        is rejected after this point; None when nothing was taken.
        """
        # A caller-supplied key spends their own quota, not ours.
        if gemini_api_key or not self._free_runs.enabled:
            return None
        device_id = self._device_tokens.verify(device_token or "")
        if device_id is None:
            raise DeviceTokenInvalidError("This device needs a fresh token. Reload and try again.")
        claim = await self._free_runs.try_consume(device_id, client_ip)
        if claim is None:
            status = await self._free_runs.status(device_id)
            # Same answer whichever counter tripped: the device's numbers.
            raise FreeRunsExhaustedError(FREE_RUNS_USED_MESSAGE, limit=status.limit, used=status.used)
        return claim

    async def _accept(
        self,
        *,
        run_id: str,
        principal: Principal,
        file: UploadedFile | None,
        source_url: str | None,
        gemini_api_key: str | None,
    ) -> Run:
        # BYOK runs skip the daily budget too: it exists purely to bound our
        # own Gemini spend.
        if not gemini_api_key and not await self._spend_cap.try_consume():
            raise QuotaExceededError(
                "VideoLens AI has reached its limit for today. Add your own Gemini key "
                "from the menu to keep going, or try again tomorrow.",
                # The budget is per UTC day (DailyBudget), so it frees at midnight UTC.
                retry_after_seconds=seconds_until_next_utc_day(datetime.now(timezone.utc)),
            )

        saved = None
        source_key = None
        platform = None
        duration_seconds = None
        try:
            if file is not None:
                saved = await self._media.save_upload(run_id, file)
                duration_seconds = await self._media.enforce_duration_cap(run_id, saved.path)
                # Only the extension of the *saved* path is consulted (the
                # adapter names it "upload<ext>"), never the submitted
                # filename, which can carry personal information.
                platform = file_platform(os.path.splitext(saved.path)[1])
                if self._distributed:
                    source_key = await self._storage.upload_source(run_id, saved.path)
                    self._media.cleanup_run_dir(run_id)

            run = await self._runs.create(
                run_id,
                principal.subject,
                source_kind="file" if file is not None else "link",
                platform=platform,
                duration_seconds=duration_seconds,
            )
            await self._queue.enqueue(
                run_id,
                saved_path=saved.path if saved and not self._distributed else None,
                run_dir=saved.run_dir if saved and not self._distributed else None,
                source_url=source_url,
                source_key=source_key,
                gemini_api_key=gemini_api_key,
            )
            return run
        except MediaValidationError:
            self._media.cleanup_run_dir(run_id)
            raise
        except Exception as exc:
            self._media.cleanup_run_dir(run_id)
            if source_key:
                await self._storage.delete_source(source_key)
            raise RunSchedulingError("VideoLens is having trouble right now. Try again in a moment.") from exc
