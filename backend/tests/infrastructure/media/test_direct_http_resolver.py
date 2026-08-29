import io
import os
import shutil
import socket
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from app.domain.errors import MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.media.resolvers.direct_http import (
    DirectHttpResolver,
    _ValidatingRedirectHandler,
)

PUBLIC_ADDRESS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
PRIVATE_ADDRESS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]


def _response(body: bytes, headers: dict | None = None) -> MagicMock:
    stream = io.BytesIO(body)
    response = MagicMock()
    response.read.side_effect = stream.read
    response.headers = headers or {}
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class CanHandleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = DirectHttpResolver(Settings())

    def test_claims_urls_that_name_a_supported_media_file(self) -> None:
        self.assertTrue(self.resolver.can_handle("https://cdn.test/clip.mp4"))
        self.assertTrue(self.resolver.can_handle("https://cdn.test/a/b/talk.MP3"))
        self.assertTrue(self.resolver.can_handle("https://cdn.test/clip.mov?token=abc"))

    def test_declines_page_urls_it_could_not_possibly_serve(self) -> None:
        self.assertFalse(self.resolver.can_handle("https://youtube.com/watch?v=abc"))
        self.assertFalse(self.resolver.can_handle("https://instagram.com/p/abc/"))
        self.assertFalse(self.resolver.can_handle("https://cdn.test/clip.mkv"))


class FetchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.settings = Settings(temp_dir=self.temp_dir, max_file_size_mb=1)
        self.resolver = DirectHttpResolver(self.settings)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PUBLIC_ADDRESS)
    @patch("app.infrastructure.media.resolvers.direct_http.urllib.request.build_opener")
    async def test_downloads_the_file_and_keeps_the_extension(self, build_opener, _dns) -> None:
        build_opener.return_value.open.return_value = _response(b"media-bytes")

        saved = await self.resolver.fetch("run-1", "https://cdn.test/clip.mp4")

        self.assertTrue(saved.path.endswith("download.mp4"))
        with open(saved.path, "rb") as handle:
            self.assertEqual(handle.read(), b"media-bytes")
        # A bare file carries no publisher information.
        self.assertIsNone(saved.metadata)

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PRIVATE_ADDRESS)
    async def test_refuses_a_url_that_resolves_into_private_space(self, _dns) -> None:
        with self.assertRaisesRegex(MediaValidationError, "private network"):
            await self.resolver.fetch("run-1", "http://metadata.test/clip.mp4")

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PUBLIC_ADDRESS)
    @patch("app.infrastructure.media.resolvers.direct_http.urllib.request.build_opener")
    async def test_rejects_a_body_larger_than_the_cap_mid_stream(self, build_opener, _dns) -> None:
        # No Content-Length, so the cap can only be enforced while reading.
        build_opener.return_value.open.return_value = _response(b"x" * (2 * 1024 * 1024))

        with self.assertRaisesRegex(MediaValidationError, "over the 1MB limit"):
            await self.resolver.fetch("run-1", "https://cdn.test/clip.mp4")

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PUBLIC_ADDRESS)
    @patch("app.infrastructure.media.resolvers.direct_http.urllib.request.build_opener")
    async def test_rejects_an_oversized_content_length_before_reading(self, build_opener, _dns) -> None:
        response = _response(b"x", headers={"Content-Length": str(50 * 1024 * 1024)})
        build_opener.return_value.open.return_value = response

        with self.assertRaisesRegex(MediaValidationError, "over the 1MB limit"):
            await self.resolver.fetch("run-1", "https://cdn.test/clip.mp4")
        response.read.assert_not_called()

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PUBLIC_ADDRESS)
    @patch("app.infrastructure.media.resolvers.direct_http.urllib.request.build_opener")
    async def test_reports_the_http_status_on_an_error_response(self, build_opener, _dns) -> None:
        build_opener.return_value.open.side_effect = urllib.error.HTTPError(
            "https://cdn.test/clip.mp4", 404, "Not Found", {}, None
        )

        with self.assertRaises(MediaValidationError) as caught:
            await self.resolver.fetch("run-1", "https://cdn.test/clip.mp4")

        # The status code is operator detail, so it belongs in the log rather
        # than on a phone screen.
        self.assertNotIn("404", str(caught.exception))
        self.assertIn("404", caught.exception.log_detail)

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PUBLIC_ADDRESS)
    @patch("app.infrastructure.media.resolvers.direct_http.urllib.request.build_opener")
    async def test_rejects_an_empty_body(self, build_opener, _dns) -> None:
        build_opener.return_value.open.return_value = _response(b"")

        with self.assertRaisesRegex(MediaValidationError, "empty file"):
            await self.resolver.fetch("run-1", "https://cdn.test/clip.mp4")

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PUBLIC_ADDRESS)
    @patch("app.infrastructure.media.resolvers.direct_http.urllib.request.build_opener")
    async def test_never_surfaces_a_transport_error_verbatim(self, build_opener, _dns) -> None:
        build_opener.return_value.open.side_effect = urllib.error.URLError(
            "connection refused by internal-host:8080"
        )

        with self.assertRaises(MediaValidationError) as caught:
            await self.resolver.fetch("run-1", "https://cdn.test/clip.mp4")
        self.assertNotIn("internal-host", str(caught.exception))
        self.assertIn("internal-host", caught.exception.log_detail)

    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PUBLIC_ADDRESS)
    @patch("app.infrastructure.media.resolvers.direct_http.urllib.request.build_opener")
    async def test_cleans_up_the_run_directory_when_the_download_fails(self, build_opener, _dns) -> None:
        build_opener.return_value.open.side_effect = urllib.error.URLError("boom")

        with self.assertRaises(MediaValidationError):
            await self.resolver.fetch("run-1", "https://cdn.test/clip.mp4")
        self.assertFalse(os.path.exists(os.path.join(self.temp_dir, "run-1")))


class RedirectValidationTests(unittest.TestCase):
    @patch("app.infrastructure.media.net.socket.getaddrinfo", return_value=PRIVATE_ADDRESS)
    def test_a_redirect_into_private_space_is_refused(self, _dns) -> None:
        handler = _ValidatingRedirectHandler()

        # Validating only the URL the caller typed would let a public host
        # bounce the fetch to the cloud metadata endpoint.
        with self.assertRaisesRegex(MediaValidationError, "private network"):
            handler.redirect_request(
                MagicMock(), MagicMock(), 302, "Found", {}, "http://169.254.169.254/latest/meta-data"
            )


if __name__ == "__main__":
    unittest.main()
