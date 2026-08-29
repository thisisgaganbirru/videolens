import socket
import unittest
from unittest.mock import patch

from app.domain.errors import MediaValidationError
from app.infrastructure.media.net import MAX_URL_LENGTH, validate_public_url


class PublicUrlValidationTests(unittest.TestCase):
    """The SSRF guard, tested where it lives now that both the yt-dlp and the
    direct-HTTP resolver share this one implementation."""

    @patch("app.infrastructure.media.net.socket.getaddrinfo")
    def test_accepts_public_https_url(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

        validate_public_url("https://example.com/video/123")

    @patch("app.infrastructure.media.net.socket.getaddrinfo")
    def test_rejects_private_network_target(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

        with self.assertRaisesRegex(MediaValidationError, "private-network"):
            validate_public_url("http://localhost/media")

    @patch("app.infrastructure.media.net.socket.getaddrinfo")
    def test_rejects_a_host_whose_second_address_is_private(self, getaddrinfo) -> None:
        # Every resolved address has to pass, not just the first one.
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
        ]

        with self.assertRaisesRegex(MediaValidationError, "private-network"):
            validate_public_url("https://dual.test/clip.mp4")

    def test_rejects_non_http_url(self) -> None:
        with self.assertRaisesRegex(MediaValidationError, "HTTP or HTTPS"):
            validate_public_url("file:///etc/passwd")

    def test_rejects_embedded_credentials(self) -> None:
        with self.assertRaisesRegex(MediaValidationError, "HTTP or HTTPS"):
            validate_public_url("https://user:pw@example.com/clip.mp4")

    def test_rejects_an_overlong_url(self) -> None:
        with self.assertRaisesRegex(MediaValidationError, "too long"):
            validate_public_url("https://example.com/" + "a" * MAX_URL_LENGTH)

    @patch("app.infrastructure.media.net.socket.getaddrinfo", side_effect=socket.gaierror)
    def test_reports_an_unresolvable_host(self, _dns) -> None:
        with self.assertRaisesRegex(MediaValidationError, "could not be found"):
            validate_public_url("https://nope.invalid/clip.mp4")


if __name__ == "__main__":
    unittest.main()
