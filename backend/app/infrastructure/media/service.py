import asyncio
import logging

from ...domain.entities import CaptionTrack, MediaVisuals, SavedUpload
from ...domain.ports import UploadedFile
from ..config import Settings
from . import captions, ffmpeg, thumbnails, uploads
from .resolvers import DirectHttpResolver, ResolverChain, YtDlpResolver

logger = logging.getLogger("videolens")

# Upper bound on the whole poster step, on top of each fetch/ffmpeg call's own
# timeout: it runs alongside the analysis and must never be what a run waits on.
VISUALS_TIMEOUT_SECONDS = 45


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

    def validate_temp_dir(self) -> None:
        uploads.validate_temp_dir(self._settings)

    def create_run_dir(self, run_id: str) -> str:
        return uploads.create_run_dir(self._settings, run_id)

    def cleanup_run_dir(self, run_id: str) -> None:
        uploads.cleanup_run_dir(self._settings, run_id)

    async def save_upload(self, run_id: str, upload: UploadedFile) -> SavedUpload:
        return await uploads.save_upload(self._settings, run_id, upload)

    async def enforce_duration_cap(self, run_id: str, path: str) -> float:
        return await ffmpeg.enforce_duration_cap(self._settings, run_id, path)

    async def download_url(self, run_id: str, url: str) -> SavedUpload:
        return await self._resolvers.fetch(run_id, url)

    async def fetch_captions(self, url: str) -> CaptionTrack | None:
        return await captions.fetch_captions(self._settings, url)

    async def normalize_media(self, src_path: str, run_dir: str) -> str:
        return await ffmpeg.normalize_media(self._settings, src_path, run_dir)

    async def describe_visuals(
        self,
        *,
        media_path: str | None = None,
        thumbnail_urls: tuple[str, ...] = (),
        width: int | None = None,
        height: int | None = None,
        duration_seconds: float | None = None,
    ) -> MediaVisuals:
        try:
            return await asyncio.wait_for(
                self._describe_visuals(
                    media_path=media_path,
                    thumbnail_urls=thumbnail_urls,
                    width=width,
                    height=height,
                    duration_seconds=duration_seconds,
                ),
                VISUALS_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - cosmetic; never fail a run over it
            logger.warning("Could not describe media visuals", exc_info=True)
            return MediaVisuals()

    async def _describe_visuals(
        self,
        *,
        media_path: str | None,
        thumbnail_urls: tuple[str, ...],
        width: int | None,
        height: int | None,
        duration_seconds: float | None,
    ) -> MediaVisuals:
        # The file is the measurement and wins; yt-dlp's reported size is the
        # fallback (and the only source on the captions path, where nothing
        # was downloaded). No video stream and no hint means audio: None.
        probed = await thumbnails.probe_dimensions(self._settings, media_path) if media_path else None
        if probed is not None:
            width, height = probed
        elif width is None or height is None:
            width = height = None
        thumbnail = await thumbnails.build_thumbnail(
            self._settings,
            thumbnail_urls=thumbnail_urls,
            media_path=media_path,
            has_video=probed is not None,
            duration_seconds=duration_seconds,
        )
        return MediaVisuals(thumbnail=thumbnail, width=width, height=height)
