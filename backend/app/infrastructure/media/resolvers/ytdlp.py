from ....domain.entities import SavedUpload
from ...config import Settings
from .. import ytdlp_downloader


class YtDlpResolver:
    """SourceResolver backed by yt-dlp - the primary path for every URL.

    Claims every URL because yt-dlp's generic extractor is itself a fallback
    for plain media links, so there is no address it can be ruled out for in
    advance. It is also the only resolver that returns publisher metadata.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "yt-dlp"

    def can_handle(self, url: str) -> bool:
        return True

    async def fetch(self, run_id: str, url: str) -> SavedUpload:
        return await ytdlp_downloader.download_url(self._settings, run_id, url)
