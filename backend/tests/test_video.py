import socket
import unittest
from unittest.mock import patch

from yt_dlp.utils import DownloadError

from app.config import settings
from app.video import (
    MediaValidationError,
    _cookie_options,
    _download_error_message,
    _validate_public_url,
)


class PublicUrlValidationTests(unittest.TestCase):
    @patch("app.video.socket.getaddrinfo")
    def test_accepts_public_https_url(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ]

        _validate_public_url("https://example.com/video/123")

    @patch("app.video.socket.getaddrinfo")
    def test_rejects_private_network_target(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]

        with self.assertRaisesRegex(MediaValidationError, "private-network"):
            _validate_public_url("http://localhost/media")

    def test_rejects_non_http_url(self) -> None:
        with self.assertRaisesRegex(MediaValidationError, "HTTP or HTTPS"):
            _validate_public_url("file:///etc/passwd")

    @patch.object(settings, "ytdlp_cookies_file", "")
    @patch.object(settings, "ytdlp_cookies_from_browser", "chrome")
    def test_builds_browser_cookie_options(self) -> None:
        self.assertEqual(
            _cookie_options(),
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


if __name__ == "__main__":
    unittest.main()
