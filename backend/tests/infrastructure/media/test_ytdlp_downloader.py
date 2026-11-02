import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from yt_dlp.utils import DownloadError

from app.domain.errors import MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.media.ytdlp_downloader import (
    _cookie_options,
    _download_failure,
    download_url,
)


class CookieAndErrorHandlingTests(unittest.TestCase):
    def test_builds_browser_cookie_options(self) -> None:
        settings = Settings(ytdlp_cookies_file="", ytdlp_cookies_from_browser="chrome")
        self.assertEqual(
            _cookie_options(settings),
            {"cookiesfrombrowser": ("chrome", None, None, None)},
        )

    def test_instagram_login_wall_becomes_a_plain_sentence(self) -> None:
        message, detail = _download_failure(
            DownloadError(
                "Instagram sent an empty media response. Check if this post is "
                "accessible in your browser without being logged-in. If it is not, "
                "then use --cookies-from-browser or --cookies for the authentication."
            )
        )

        self.assertEqual(
            message, "This post isn't public - Instagram only serves it to signed-in viewers."
        )
        # yt-dlp's own advice is for whoever runs yt-dlp, so it belongs in the
        # log and must not survive into the message shown on a phone.
        self.assertNotIn("--cookies", message)
        self.assertIn("--cookies-from-browser", detail)

    def test_youtube_bot_check_becomes_a_plain_sentence(self) -> None:
        message, detail = _download_failure(
            DownloadError("Sign in to confirm you're not a bot. Use --cookies-from-browser.")
        )

        self.assertEqual(message, "YouTube is blocking automated downloads from this server.")
        self.assertIn("not a bot", detail)

    def test_unrecognised_failure_keeps_its_detail_out_of_the_message(self) -> None:
        message, detail = _download_failure(
            DownloadError("\x1b[0;31mERROR:\x1b[0m merging failed")
        )

        self.assertEqual(
            message,
            "This link couldn't be downloaded. It may be private, deleted, or region-locked.",
        )
        # ANSI colours stripped, "ERROR: " prefix dropped, text preserved for the log.
        self.assertEqual(detail, "merging failed")


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


class FormatCapTests(unittest.IsolatedAsyncioTestCase):
    """The options handed to YoutubeDL: a 720p soft cap via format_sort."""

    async def _options_for(self, settings: Settings) -> dict:
        downloaded_path = os.path.join(settings.temp_dir, "download.mp4")
        with open(downloaded_path, "wb") as fh:
            fh.write(b"fake video bytes")
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.__exit__.return_value = False
        downloader.extract_info.return_value = {"requested_downloads": [{"filepath": downloaded_path}]}
        downloader.prepare_filename.return_value = downloaded_path
        with patch(
            "app.infrastructure.media.ytdlp_downloader.validate_public_url"
        ), patch(
            "app.infrastructure.media.ytdlp_downloader._media_binary",
            return_value=os.path.join("opt", "ffmpeg", "bin", "ffmpeg"),
        ), patch(
            "app.infrastructure.media.ytdlp_downloader.YoutubeDL", return_value=downloader
        ) as youtube_dl:
            await download_url(settings, "run-fmt", "https://www.youtube.com/watch?v=x")
        return youtube_dl.call_args.args[0]

    async def test_defaults_to_a_720p_soft_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            options = await self._options_for(
                Settings(temp_dir=temp_dir, ytdlp_cookies_file="", ytdlp_cookies_from_browser="")
            )

        self.assertEqual(options["format_sort"], ["res:720"])
        # Selector keeps every fallback: split streams, progressive file, audio only.
        self.assertEqual(options["format"], "bestvideo*+bestaudio/best/bestaudio")
        # No hard height filter in the selector - it would reject sources with
        # no <=720p variant and drop formats of unknown height.
        self.assertNotIn("height", options["format"])
        # Merging split streams still uses the configured FFmpeg.
        self.assertEqual(options["ffmpeg_location"], os.path.join("opt", "ffmpeg", "bin"))

    async def test_cap_follows_the_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            options = await self._options_for(
                Settings(
                    temp_dir=temp_dir,
                    ytdlp_cookies_file="",
                    ytdlp_cookies_from_browser="",
                    ytdlp_max_height=480,
                )
            )

        self.assertEqual(options["format_sort"], ["res:480"])

    async def test_zero_removes_the_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            options = await self._options_for(
                Settings(
                    temp_dir=temp_dir,
                    ytdlp_cookies_file="",
                    ytdlp_cookies_from_browser="",
                    ytdlp_max_height=0,
                )
            )

        self.assertNotIn("format_sort", options)
        self.assertEqual(options["format"], "bestvideo*+bestaudio/best/bestaudio")


if __name__ == "__main__":
    unittest.main()
