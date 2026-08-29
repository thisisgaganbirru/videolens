import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from yt_dlp.utils import DownloadError

from app.domain.errors import MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.media.ytdlp_downloader import (
    _cookie_options,
    _download_error_message,
    download_url,
)


class CookieAndErrorHandlingTests(unittest.TestCase):
    def test_builds_browser_cookie_options(self) -> None:
        settings = Settings(ytdlp_cookies_file="", ytdlp_cookies_from_browser="chrome")
        self.assertEqual(
            _cookie_options(settings),
            {"cookiesfrombrowser": ("chrome", None, None, None)},
        )

    def test_shortens_instagram_authentication_error(self) -> None:
        message = _download_error_message(
            DownloadError("Instagram sent an empty media response. Long diagnostic text.")
        )

        self.assertIn("login cookies", message)
        self.assertNotIn("Long diagnostic", message)

    def test_removes_terminal_colors_from_download_error(self) -> None:
        message = _download_error_message(
            DownloadError("\x1b[0;31mERROR:\x1b[0m merging failed")
        )

        self.assertEqual(message, "Could not download media from this URL. merging failed")


class SourceMetadataExtractionTests(unittest.IsolatedAsyncioTestCase):
    def _settings(self, temp_dir: str) -> Settings:
        return Settings(temp_dir=temp_dir, ytdlp_cookies_file="", ytdlp_cookies_from_browser="")

    def _mock_downloader(self, info: dict, downloaded_path: str):
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.__exit__.return_value = False
        downloader.extract_info.return_value = info
        downloader.prepare_filename.return_value = downloaded_path
        return downloader

    async def test_maps_full_metadata_from_info_dict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(temp_dir)
            downloaded_path = os.path.join(temp_dir, "download.mp4")
            with open(downloaded_path, "wb") as fh:
                fh.write(b"fake video bytes")

            info = {
                "extractor_key": "Instagram",
                "title": "Building an AI MVP",
                "uploader": "thenivassalla",
                "uploader_url": "https://www.instagram.com/thenivassalla/",
                "description": "How we built it overnight.",
                "upload_date": "20260101",
                "like_count": 1200,
                "view_count": 50000,
                "comment_count": 42,
                "requested_downloads": [{"filepath": downloaded_path}],
            }
            downloader = self._mock_downloader(info, downloaded_path)

            with patch(
                "app.infrastructure.media.ytdlp_downloader.validate_public_url"
            ), patch(
                "app.infrastructure.media.ytdlp_downloader._media_binary", return_value="/usr/bin/ffmpeg"
            ), patch(
                "app.infrastructure.media.ytdlp_downloader.YoutubeDL", return_value=downloader
            ):
                saved = await download_url(settings, "run-1", "https://www.instagram.com/reel/abc/")

            self.assertIsNotNone(saved.metadata)
            self.assertEqual(saved.metadata.platform, "Instagram")
            self.assertEqual(saved.metadata.source_url, "https://www.instagram.com/reel/abc/")
            self.assertEqual(saved.metadata.title, "Building an AI MVP")
            self.assertEqual(saved.metadata.uploader, "thenivassalla")
            self.assertEqual(saved.metadata.uploader_url, "https://www.instagram.com/thenivassalla/")
            self.assertEqual(saved.metadata.description, "How we built it overnight.")
            self.assertEqual(saved.metadata.upload_date, "20260101")
            self.assertEqual(saved.metadata.like_count, 1200)
            self.assertEqual(saved.metadata.view_count, 50000)
            self.assertEqual(saved.metadata.comment_count, 42)

    async def test_missing_fields_become_none_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(temp_dir)
            downloaded_path = os.path.join(temp_dir, "download.mp3")
            with open(downloaded_path, "wb") as fh:
                fh.write(b"fake audio bytes")

            info = {"requested_downloads": [{"filepath": downloaded_path}]}
            downloader = self._mock_downloader(info, downloaded_path)

            with patch(
                "app.infrastructure.media.ytdlp_downloader.validate_public_url"
            ), patch(
                "app.infrastructure.media.ytdlp_downloader._media_binary", return_value="/usr/bin/ffmpeg"
            ), patch(
                "app.infrastructure.media.ytdlp_downloader.YoutubeDL", return_value=downloader
            ):
                saved = await download_url(settings, "run-2", "https://example.com/clip")

            self.assertIsNotNone(saved.metadata)
            self.assertEqual(saved.metadata.platform, "unknown")
            self.assertEqual(saved.metadata.source_url, "https://example.com/clip")
            self.assertIsNone(saved.metadata.title)
            self.assertIsNone(saved.metadata.uploader)
            self.assertIsNone(saved.metadata.like_count)


if __name__ == "__main__":
    unittest.main()
