"""In-memory test doubles for the domain ports. Each fake implements exactly
the Protocol methods application-layer tests need, plus a bit of call
tracking so tests can assert on how a use case drove its dependencies."""

from datetime import datetime, timezone

from app.domain.entities import (
    AnalysisCompleteness,
    CaptionTrack,
    MediaVisuals,
    Run,
    RunStatus,
    SavedUpload,
    SourceMetadata,
)


class FakeRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}
        self.created_ids: list[str] = []
        self.set_visuals_error: Exception | None = None
        self.visuals_written_while: list[RunStatus] = []

    async def create(
        self,
        run_id: str,
        owner_id: str,
        *,
        source_kind: str | None = None,
        platform: str | None = None,
        duration_seconds: float | None = None,
    ) -> Run:
        now = datetime.now(timezone.utc)
        run = Run(
            run_id=run_id,
            owner_id=owner_id,
            status=RunStatus.QUEUED,
            created_at=now,
            updated_at=now,
            source_kind=source_kind,
            platform=platform,
            duration_seconds=duration_seconds,
        )
        self.runs[run_id] = run
        self.created_ids.append(run_id)
        return run

    async def get(self, run_id: str):
        return self.runs.get(run_id)

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]:
        matches = [run for run in self.runs.values() if run.owner_id == owner_id]
        return matches[:limit]

    async def set_status(self, run_id: str, status: RunStatus) -> None:
        self.runs[run_id].status = status

    async def set_stage(self, run_id: str, stage: str) -> None:
        self.runs[run_id].stage = stage

    async def set_result(
        self, run_id: str, result, completeness=AnalysisCompleteness.FULL
    ) -> None:
        self.runs[run_id].status = RunStatus.COMPLETE
        self.runs[run_id].result = result
        self.runs[run_id].completeness = completeness

    async def set_source_metadata(self, run_id: str, metadata: SourceMetadata) -> None:
        self.runs[run_id].source_metadata = metadata

    async def set_duration(self, run_id: str, duration_seconds: float) -> None:
        self.runs[run_id].duration_seconds = duration_seconds

    async def set_visuals(self, run_id: str, visuals: MediaVisuals) -> None:
        if self.set_visuals_error:
            raise self.set_visuals_error
        run = self.runs[run_id]
        # Visuals land before the status flips: record what the run looked like.
        self.visuals_written_while.append(run.status)
        run.thumbnail = visuals.thumbnail
        run.width = visuals.width
        run.height = visuals.height

    async def set_error(self, run_id: str, error: str) -> None:
        self.runs[run_id].status = RunStatus.FAILED
        self.runs[run_id].error = error

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class FakeMediaProcessor:
    def __init__(self) -> None:
        self.validated = False
        self.cleaned_up: list[str] = []
        self.enforced_duration: list[tuple[str, str]] = []
        self.download_calls: list[tuple[str, str]] = []
        self.normalize_calls: list[tuple[str, str]] = []
        self.save_upload_error: Exception | None = None
        self.enforce_duration_error: Exception | None = None
        self.probed_duration: float = 42.5
        self.upload_extension: str = ".mp4"
        self.download_error: Exception | None = None
        self.download_metadata: SourceMetadata | None = None
        self.captions: CaptionTrack | None = None
        self.caption_calls: list[str] = []
        self.captions_error: Exception | None = None
        self.download_thumbnail_urls: tuple[str, ...] = ()
        self.download_dims: tuple[int | None, int | None] = (None, None)
        self.visuals = MediaVisuals(thumbnail="data:image/jpeg;base64,AAAA", width=1280, height=720)
        self.visuals_error: BaseException | None = None
        self.visuals_calls: list[dict] = []

    def validate_tools(self) -> None:
        self.validated = True

    def create_run_dir(self, run_id: str) -> str:
        return f"/tmp/{run_id}"

    def cleanup_run_dir(self, run_id: str) -> None:
        self.cleaned_up.append(run_id)

    async def save_upload(self, run_id: str, upload) -> SavedUpload:
        if self.save_upload_error:
            raise self.save_upload_error
        return SavedUpload(
            path=f"/tmp/{run_id}/upload{self.upload_extension}", run_dir=f"/tmp/{run_id}"
        )

    async def enforce_duration_cap(self, run_id: str, path: str) -> float:
        self.enforced_duration.append((run_id, path))
        if self.enforce_duration_error:
            raise self.enforce_duration_error
        return self.probed_duration

    async def download_url(self, run_id: str, url: str) -> SavedUpload:
        self.download_calls.append((run_id, url))
        if self.download_error:
            raise self.download_error
        return SavedUpload(
            path=f"/tmp/{run_id}/download.mp4",
            run_dir=f"/tmp/{run_id}",
            metadata=self.download_metadata,
            thumbnail_urls=self.download_thumbnail_urls,
            width=self.download_dims[0],
            height=self.download_dims[1],
        )

    async def fetch_captions(self, url: str) -> CaptionTrack | None:
        self.caption_calls.append(url)
        if self.captions_error:
            raise self.captions_error
        return self.captions

    async def normalize_media(self, src_path: str, run_dir: str) -> str:
        self.normalize_calls.append((src_path, run_dir))
        return f"{run_dir}/normalized.mp4"

    async def describe_visuals(self, **kwargs) -> MediaVisuals:
        self.visuals_calls.append(kwargs)
        if self.visuals_error:
            raise self.visuals_error
        return self.visuals


class FakeObjectStore:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self.uploaded: dict[str, str] = {}
        self.downloaded: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.upload_source_error: Exception | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def upload_source(self, run_id: str, path: str) -> str:
        if self.upload_source_error:
            raise self.upload_source_error
        key = f"runs/{run_id}/source.mp4"
        self.uploaded[run_id] = key
        return key

    async def download_source(self, key: str, destination: str) -> None:
        self.downloaded.append((key, destination))

    async def delete_source(self, key: str) -> None:
        self.deleted.append(key)


class RaisingObjectStore(FakeObjectStore):
    """An object store whose delete_source always fails - used to prove
    ProcessRunUseCase's cleanup doesn't get short-circuited by it."""

    async def delete_source(self, key: str) -> None:
        raise RuntimeError("S3 is down")


class FakeJobQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []
        self.closed = False
        self.enqueue_error: Exception | None = None

    async def enqueue(
        self,
        run_id: str,
        *,
        saved_path: str | None = None,
        run_dir: str | None = None,
        source_url: str | None = None,
        source_key: str | None = None,
        gemini_api_key: str | None = None,
    ) -> None:
        if self.enqueue_error:
            raise self.enqueue_error
        self.enqueued.append(
            dict(
                run_id=run_id,
                saved_path=saved_path,
                run_dir=run_dir,
                source_url=source_url,
                source_key=source_key,
                gemini_api_key=gemini_api_key,
            )
        )

    async def close(self) -> None:
        self.closed = True


class FakeSpendCap:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.consume_calls = 0

    async def try_consume(self) -> bool:
        self.consume_calls += 1
        return self.allow

    async def close(self) -> None:
        pass


class FakeAnalysisEngine:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str | None]] = []
        self.stages_seen: list[str] = []
        self.metadata_seen: list[SourceMetadata | None] = []
        self.caption_calls: list[CaptionTrack] = []
        self.caption_result = None
        self.caption_error: Exception | None = None

    async def analyze_with_retry(
        self,
        video_path: str,
        on_stage=None,
        api_key: str | None = None,
        metadata: SourceMetadata | None = None,
    ):
        self.calls.append((video_path, api_key))
        self.metadata_seen.append(metadata)
        if on_stage:
            await on_stage("uploading_to_gemini")
            self.stages_seen.append("uploading_to_gemini")
            await on_stage("analyzing")
            self.stages_seen.append("analyzing")
        if self.error:
            raise self.error
        return self.result

    async def analyze_captions(self, captions, api_key: str | None = None):
        self.caption_calls.append(captions)
        if self.caption_error:
            raise self.caption_error
        return self.caption_result or self.result


class FakeUploadedFile:
    def __init__(self, filename: str = "upload.mp4") -> None:
        self.filename = filename
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        return b""

    async def close(self) -> None:
        self.closed = True
