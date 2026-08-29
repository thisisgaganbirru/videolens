from ...domain.entities import SavedUpload
from ...domain.ports import UploadedFile
from ..config import Settings
from . import ffmpeg, uploads
from .resolvers import DirectHttpResolver, ResolverChain, YtDlpResolver


class MediaService:
    """MediaProcessor adapter: delegates to the FFmpeg, URL-resolver, and
    upload-handling pieces, each of which owns one part of the media
    lifecycle (validate tools, save/download source, normalize)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Order is the contract. yt-dlp stays first so nothing that works
        # today changes behaviour; direct HTTP only ever runs after it has
        # already failed on a link that names a media file outright.
        self._resolvers = ResolverChain(
            [YtDlpResolver(settings), DirectHttpResolver(settings)]
        )

    def validate_tools(self) -> None:
        ffmpeg.validate_media_tools(self._settings)

    def create_run_dir(self, run_id: str) -> str:
        return uploads.create_run_dir(self._settings, run_id)

    def cleanup_run_dir(self, run_id: str) -> None:
        uploads.cleanup_run_dir(self._settings, run_id)

    async def save_upload(self, run_id: str, upload: UploadedFile) -> SavedUpload:
        return await uploads.save_upload(self._settings, run_id, upload)

    async def enforce_duration_cap(self, run_id: str, path: str) -> None:
        await ffmpeg.enforce_duration_cap(self._settings, run_id, path)

    async def download_url(self, run_id: str, url: str) -> SavedUpload:
        return await self._resolvers.fetch(run_id, url)

    async def normalize_media(self, src_path: str, run_dir: str) -> str:
        return await ffmpeg.normalize_media(self._settings, src_path, run_dir)
