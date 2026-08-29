"""Interfaces the application layer depends on. Infrastructure adapters
implement these structurally (Protocol = duck typing, no inheritance
required) so use cases never import a framework or a driver library."""

from typing import Awaitable, Callable, Optional, Protocol

from .entities import (
    Capability,
    Run,
    RunStatus,
    SavedUpload,
    SourceMetadata,
    VideoAnalysis,
)

StageCallback = Callable[[str], Awaitable[None]]


class UploadedFile(Protocol):
    """Whatever the caller submitted as a file. FastAPI's UploadFile
    satisfies this structurally, without the domain importing FastAPI."""

    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...

    async def close(self) -> None: ...


class RunRepository(Protocol):
    async def create(self, run_id: str, owner_id: str) -> Run: ...

    async def get(self, run_id: str) -> Optional[Run]: ...

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]: ...

    async def set_status(self, run_id: str, status: RunStatus) -> None: ...

    async def set_stage(self, run_id: str, stage: str) -> None: ...

    async def set_result(self, run_id: str, result: VideoAnalysis) -> None: ...

    async def set_source_metadata(self, run_id: str, metadata: SourceMetadata) -> None: ...

    async def set_error(self, run_id: str, error: str) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class MediaProcessor(Protocol):
    def validate_tools(self) -> None: ...

    def create_run_dir(self, run_id: str) -> str: ...

    def cleanup_run_dir(self, run_id: str) -> None: ...

    async def save_upload(self, run_id: str, upload: UploadedFile) -> SavedUpload: ...

    async def enforce_duration_cap(self, run_id: str, path: str) -> None: ...

    async def download_url(self, run_id: str, url: str) -> SavedUpload: ...

    async def normalize_media(self, src_path: str, run_dir: str) -> str: ...


class SourceResolver(Protocol):
    """One route to the media behind a URL. Several may exist for the same
    source; the chain that owns them decides the order and moves on to the
    next when one fails."""

    @property
    def name(self) -> str: ...

    def can_handle(self, url: str) -> bool: ...

    async def fetch(self, run_id: str, url: str) -> SavedUpload: ...


class AnalysisEngine(Protocol):
    async def analyze_with_retry(
        self,
        video_path: str,
        on_stage: Optional[StageCallback] = None,
        api_key: str | None = None,
        metadata: Optional[SourceMetadata] = None,
    ) -> VideoAnalysis: ...


class ObjectStore(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def upload_source(self, run_id: str, path: str) -> str: ...

    async def download_source(self, key: str, destination: str) -> None: ...

    async def delete_source(self, key: str) -> None: ...


class JobQueue(Protocol):
    async def enqueue(
        self,
        run_id: str,
        *,
        saved_path: str | None = None,
        run_dir: str | None = None,
        source_url: str | None = None,
        source_key: str | None = None,
        gemini_api_key: str | None = None,
    ) -> None: ...

    async def close(self) -> None: ...


class SpendCap(Protocol):
    async def try_consume(self) -> bool: ...

    async def close(self) -> None: ...


class KeyVault(Protocol):
    async def store(self, run_id: str, api_key: str) -> None: ...

    async def take(self, run_id: str) -> str | None: ...

    async def close(self) -> None: ...


class TokenVerifier(Protocol):
    def decode(self, token: str) -> dict: ...


class CapabilityProbe(Protocol):
    """One health check. Adapters own the knowledge of what "working"
    means for their dependency; the application layer only aggregates."""

    @property
    def name(self) -> str: ...

    async def check(self) -> Capability: ...

