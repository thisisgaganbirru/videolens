import uuid

from ..domain.entities import Principal, Run
from ..domain.errors import (
    InvalidSourceError,
    MediaValidationError,
    QuotaExceededError,
    RunSchedulingError,
    TermsNotAcceptedError,
)
from ..domain.ports import JobQueue, MediaProcessor, ObjectStore, RunRepository, SpendCap, UploadedFile


class CreateRunUseCase:
    """Accepts a media source (file or URL), applies the intake business
    rules (terms accepted, exactly one source, daily spend cap), and
    schedules the run for analysis.

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
        distributed: bool,
    ) -> None:
        self._runs = runs
        self._media = media
        self._storage = storage
        self._queue = queue
        self._spend_cap = spend_cap
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

        # A caller-supplied key spends their own quota, not ours, so it's exempt
        # from the daily budget backstop (which exists purely to bound our own
        # Gemini spend).
        if not gemini_api_key and not await self._spend_cap.try_consume():
            raise QuotaExceededError(
                "VideoLens AI has reached its analysis limit for today. Please try again tomorrow."
            )

        run_id = str(uuid.uuid4())
        source_url = url.strip() if url else None
        if (file is None) == (source_url is None):
            if file is not None:
                await file.close()
            raise InvalidSourceError("Provide exactly one source: either a media file or a public URL.")

        saved = None
        source_key = None
        try:
            if file is not None:
                saved = await self._media.save_upload(run_id, file)
                await self._media.enforce_duration_cap(run_id, saved.path)
                if self._distributed:
                    source_key = await self._storage.upload_source(run_id, saved.path)
                    self._media.cleanup_run_dir(run_id)

            run = await self._runs.create(run_id, principal.subject)
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
            raise RunSchedulingError("Could not queue the analysis run.") from exc
