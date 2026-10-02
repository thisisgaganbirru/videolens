import uuid

from ..domain.entities import Principal, Run
from ..domain.entitlements import Plan, can_start_run
from ..domain.errors import (
    InvalidSourceError,
    MediaValidationError,
    PlanLimitError,
    QuotaExceededError,
    RunSchedulingError,
    TermsNotAcceptedError,
)
from ..domain.ports import JobQueue, MediaProcessor, ObjectStore, RunRepository, SpendCap, UploadedFile
from .entitlements import EntitlementResolver


class CreateRunUseCase:
    """Accepts a media source (file or URL), applies the intake business
    rules (terms accepted, exactly one source, plan allowance, daily spend
    cap), and schedules the run for analysis.

    Two independent budgets gate a run. The workspace's plan allowance is
    per-customer and answered with 402; the shared daily spend cap is the
    deployment's own backstop and answered with 503. Paid plans are exempt
    from the second because their minutes are billed rather than absorbed,
    and a caller-supplied Gemini key is exempt from both because it spends
    the caller's quota, not ours.

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
        entitlements: EntitlementResolver,
        distributed: bool,
    ) -> None:
        self._runs = runs
        self._media = media
        self._storage = storage
        self._queue = queue
        self._spend_cap = spend_cap
        self._entitlements = entitlements
        self._distributed = distributed

    async def execute(
        self,
        *,
        principal: Principal,
        accept_terms: bool,
        file: UploadedFile | None,
        url: str | None,
        gemini_api_key: str | None,
    ) -> Run:
        if not accept_terms:
            raise TermsNotAcceptedError("Accept the media-use terms before analysis.")

        workspace = await self._entitlements.workspace_for(principal)
        entitlement = self._entitlements.for_workspace(workspace, principal.plan)

        if not gemini_api_key and workspace is not None and entitlement.metered:
            used = await self._entitlements.minutes_used(workspace)
            if not can_start_run(entitlement, used):
                raise PlanLimitError(
                    f"Your workspace has used its {entitlement.minutes_included} included "
                    "minutes for this period. Upgrade to keep analyzing, or add your own "
                    "Gemini key from the menu."
                )

        # A caller-supplied key spends their own quota, not ours, so it's exempt
        # from the daily budget backstop (which exists purely to bound our own
        # Gemini spend). So is a paid plan: those minutes are invoiced.
        if (
            not gemini_api_key
            and entitlement.plan is Plan.FREE
            and not await self._spend_cap.try_consume()
        ):
            raise QuotaExceededError(
                "VideoLens AI has reached its limit for today. Add your own Gemini key "
                "from the menu to keep going, or try again tomorrow."
            )

        run_id = str(uuid.uuid4())
        source_url = url.strip() if url else None
        if (file is None) == (source_url is None):
            if file is not None:
                await file.close()
            raise InvalidSourceError("Provide exactly one source: either a media file or a public URL.")

        saved = None
        source_key = None
        duration = None
        try:
            if file is not None:
                saved = await self._media.save_upload(
                    run_id, file, max_size_mb=entitlement.max_file_size_mb
                )
                duration = await self._media.enforce_duration_cap(
                    run_id, saved.path, entitlement.max_duration_seconds
                )
                if self._distributed:
                    source_key = await self._storage.upload_source(run_id, saved.path)
                    self._media.cleanup_run_dir(run_id)

            run = await self._runs.create(
                run_id,
                principal.owner_id,
                workspace_id=principal.workspace_id,
                plan=entitlement.plan,
                max_duration_seconds=entitlement.max_duration_seconds,
                source_url=source_url,
            )
            if duration is not None:
                await self._runs.set_duration(run_id, duration)
                run.duration_seconds = duration
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
