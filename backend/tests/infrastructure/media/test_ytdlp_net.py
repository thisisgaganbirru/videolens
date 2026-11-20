import gzip
import io
import socket
import unittest
import zlib
from unittest.mock import patch

import yt_dlp.downloader.hls as yt_hls
from yt_dlp import YoutubeDL
from yt_dlp.networking.exceptions import RequestError, TransportError
from yt_dlp.utils import DownloadError

from app.domain.errors import MediaValidationError
from app.infrastructure.media.ytdlp_net import (
    GuardedYoutubeDL,
    PublicUrllibRH,
    _RefusedFFmpegFD,
)

_ADDRESSES = {
    "cdn.test": "93.184.216.34",
    "meta.test": "169.254.169.254",
    "internal.test": "10.0.0.5",
    "loop.test": "127.0.0.1",
}


def _resolve(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_ADDRESSES[host], port))]


class _FakeSocket:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def sendall(self, _data) -> None:
        pass

    def makefile(self, *_args, **_kwargs):
        return io.BytesIO(self._raw)

    def setsockopt(self, *_args) -> None:
        pass

    def close(self) -> None:
        pass


def _response(status: str, headers: dict, body: bytes = b"") -> bytes:
    lines = [f"HTTP/1.1 {status}"] + [f"{k}: {v}" for k, v in headers.items()]
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


def _ydl(**params) -> GuardedYoutubeDL:
    return GuardedYoutubeDL({"quiet": True, "no_warnings": True, "proxy": "", **params})


def _refused(exc: BaseException) -> bool:
    """yt-dlp may surface the guard's error as itself or wrapped."""
    while exc is not None:
        if isinstance(exc, MediaValidationError):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


@patch("app.infrastructure.media.net.socket.getaddrinfo", side_effect=_resolve)
class YtDlpRequestGuardTests(unittest.TestCase):
    """Every request yt-dlp issues - page, manifest, fragment, subtitle -
    goes through `ydl.urlopen`, so the guard is tested there."""

    def test_the_director_holds_only_the_guarded_handler(self, _dns) -> None:
        with _ydl() as ydl:
            handlers = list(ydl._request_director.handlers.values())
        self.assertEqual([type(handler) for handler in handlers], [PublicUrllibRH])

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_refuses_private_targets_without_connecting(self, connect, _dns) -> None:
        for url in ("http://meta.test/latest/", "https://internal.test/", "http://loop.test:8080/"):
            with _ydl() as ydl, self.assertRaises(Exception, msg=url) as caught:
                ydl.urlopen(url)
            self.assertTrue(_refused(caught.exception), (url, caught.exception))
        connect.assert_not_called()

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_a_public_target_is_dialled_at_the_approved_address(self, connect, _dns) -> None:
        connect.return_value = _FakeSocket(_response("200 OK", {"Content-Length": "2"}, b"ok"))

        with _ydl() as ydl:
            body = ydl.urlopen("http://cdn.test/master.m3u8").read()

        self.assertEqual(body, b"ok")
        self.assertEqual(connect.call_args.args[0], ("93.184.216.34", 80))

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_refuses_a_redirect_to_a_private_address(self, connect, _dns) -> None:
        connect.return_value = _FakeSocket(
            _response("302 Found", {"Location": "http://meta.test/latest/", "Content-Length": "0"})
        )

        with _ydl() as ydl, self.assertRaises(Exception) as caught:
            ydl.urlopen("http://cdn.test/video.mp4")

        self.assertTrue(_refused(caught.exception), caught.exception)
        connect.assert_called_once()  # the public first hop only

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_a_rebinding_name_is_refused_at_connect_time(self, connect, _dns) -> None:
        # The name answers a public address to the pre-flight check and a
        # private one afterwards: the connection resolves for itself, so it
        # sees the private answer and refuses.
        answers = iter(["93.184.216.34", "169.254.169.254"])
        with patch(
            "app.infrastructure.media.net.socket.getaddrinfo",
            side_effect=lambda host, port, *a, **k: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers), port))
            ],
        ):
            from app.infrastructure.media.net import validate_public_url

            validate_public_url("http://rebind.test/")  # what the caller checked
            with _ydl() as ydl, self.assertRaises(Exception) as caught:
                ydl.urlopen("http://rebind.test/")

        self.assertTrue(_refused(caught.exception), caught.exception)
        connect.assert_not_called()

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_through_a_proxy_the_url_is_still_checked(self, connect, _dns) -> None:
        with _ydl(proxy="http://proxy.test:3128") as ydl, self.assertRaises(Exception) as caught:
            ydl.urlopen("http://meta.test/latest/")

        self.assertTrue(_refused(caught.exception), caught.exception)
        connect.assert_not_called()

    def test_file_and_ftp_urls_are_not_supported(self, _dns) -> None:
        for url in ("file:///etc/passwd", "ftp://cdn.test/a.mp4"):
            with _ydl() as ydl, self.assertRaises(RequestError, msg=url):
                ydl.urlopen(url)


@patch("app.infrastructure.media.ytdlp_net.MAX_UNSIZED_READ_BYTES", 1000)
@patch("app.infrastructure.media.net.socket.getaddrinfo", side_effect=_resolve)
@patch("app.infrastructure.media.net.socket.create_connection")
class YtDlpReadCeilingTests(unittest.TestCase):
    """A page or API response read whole (`urlh.read()`, as extractors do)
    is bounded; media read in fixed-size chunks is not. The ceiling is
    patched down to 1000 bytes here."""

    def test_an_unsized_read_past_the_ceiling_is_refused(self, connect, _dns) -> None:
        connect.return_value = _FakeSocket(_response("200 OK", {"Content-Length": "5000"}, b"x" * 5000))
        with _ydl() as ydl:
            response = ydl.urlopen("http://cdn.test/page")
            with self.assertRaisesRegex(TransportError, "over the"):
                response.read()

    def test_a_close_delimited_body_is_bounded_too(self, connect, _dns) -> None:
        # No Content-Length: the server decides when it ends.
        connect.return_value = _FakeSocket(_response("200 OK", {"Connection": "close"}, b"x" * 5000))
        with _ydl() as ydl, self.assertRaises(TransportError):
            ydl.urlopen("http://cdn.test/page").read()

    def test_an_unsized_read_within_the_ceiling_is_the_whole_body(self, connect, _dns) -> None:
        connect.return_value = _FakeSocket(_response("200 OK", {"Content-Length": "1000"}, b"y" * 1000))
        with _ydl() as ydl:
            response = ydl.urlopen("http://cdn.test/page")
            self.assertEqual(response.read(), b"y" * 1000)
            self.assertEqual(response.read(), b"")

    def test_chunked_reads_like_a_media_download_are_not_capped(self, connect, _dns) -> None:
        connect.return_value = _FakeSocket(_response("200 OK", {"Content-Length": "5000"}, b"z" * 5000))
        with _ydl() as ydl:
            response = ydl.urlopen("http://cdn.test/a.mp4")
            total = 0
            while chunk := response.read(256):
                total += len(chunk)
        self.assertEqual(total, 5000)

    def test_a_compressed_body_is_bounded_before_and_after_decoding(self, connect, _dns) -> None:
        # yt-dlp's handler reads and decodes a gzip/deflate body whole inside
        # urlopen, before any caller's read: 200 KB of zeros is ~200 bytes of gzip.
        bomb = gzip.compress(bytes(1) * 200_000)
        self.assertLess(len(bomb), 1000)
        for encoding, body in (("gzip", bomb), ("deflate", zlib.compress(bytes(1) * 200_000))):
            connect.return_value = _FakeSocket(
                _response("200 OK", {"Content-Length": str(len(body)), "Content-Encoding": encoding}, body)
            )
            with _ydl() as ydl, self.assertRaises(Exception, msg=encoding) as caught:
                ydl.urlopen("http://cdn.test/page").read()
            self.assertIn("over the", str(caught.exception), encoding)

    def test_a_compressed_body_within_the_ceiling_still_decodes(self, connect, _dns) -> None:
        body = gzip.compress(b"hello " * 100)
        connect.return_value = _FakeSocket(
            _response("200 OK", {"Content-Length": str(len(body)), "Content-Encoding": "gzip"}, body)
        )
        with _ydl() as ydl:
            self.assertEqual(ydl.urlopen("http://cdn.test/page").read(), b"hello " * 100)

    def test_a_raw_body_over_the_ceiling_is_refused_before_decoding(self, connect, _dns) -> None:
        body = bytes([0x1F, 0x8B]) + b"x" * 5000  # never decoded: refused on size first
        connect.return_value = _FakeSocket(
            _response("200 OK", {"Content-Length": str(len(body)), "Content-Encoding": "gzip"}, body)
        )
        with _ydl() as ydl, self.assertRaises(Exception) as caught:
            ydl.urlopen("http://cdn.test/page")
        self.assertIn("over the", str(caught.exception))


class YtDlpDownloaderGuardTests(unittest.TestCase):
    """Downloaders that open their own sockets (ffmpeg, rtmpdump, external
    tools) would take a remote URL past the request guard."""

    def test_native_hls_is_preferred_and_external_downloaders_are_dropped(self) -> None:
        ydl = _ydl(external_downloader={"default": "ffmpeg"})
        self.assertTrue(ydl.params["hls_prefer_native"])
        self.assertNotIn("external_downloader", ydl.params)

    def test_refuses_ffmpeg_for_a_live_stream(self) -> None:
        info = {"url": "https://cdn.test/live.m3u8", "protocol": "m3u8_native", "is_live": True}
        with _ydl() as ydl, self.assertRaisesRegex(DownloadError, "FFmpegFD"):
            ydl.dl("out.mp4", info)

    def test_refuses_rtmp(self) -> None:
        info = {"url": "rtmp://cdn.test/app/stream", "protocol": "rtmp"}
        with _ydl() as ydl, self.assertRaisesRegex(DownloadError, "RtmpFD"):
            ydl.dl("out.mp4", info)

    def test_refuses_ffmpeg_for_a_format_check_too(self) -> None:
        # `test=True` runs with yt-dlp's own test params, which drop
        # hls_prefer_native; an `m3u8` format would go to ffmpeg there.
        info = {"url": "https://cdn.test/a.m3u8", "protocol": "m3u8"}
        with _ydl() as ydl, self.assertRaisesRegex(DownloadError, "FFmpegFD"):
            ydl.dl("out.mp4", info, test=True)

    def test_native_downloaders_are_let_through(self) -> None:
        cases = (
            {"url": "https://cdn.test/a.mp4", "protocol": "https"},
            {"url": "https://cdn.test/a.m3u8", "protocol": "m3u8"},
            {"url": "https://cdn.test/a.m3u8", "protocol": "m3u8_native"},
            {"url": "https://cdn.test/a.mpd", "protocol": "http_dash_segments"},
        )
        with patch.object(YoutubeDL, "dl", return_value=True) as parent, _ydl() as ydl:
            for info in cases:
                self.assertTrue(ydl.dl("out.mp4", info), info)
        self.assertEqual(parent.call_count, len(cases))

    def test_the_native_hls_fallback_to_ffmpeg_is_refused(self) -> None:
        self.assertIs(yt_hls.FFmpegFD, _RefusedFFmpegFD)
        with _ydl() as ydl:
            fd = _RefusedFFmpegFD(ydl, ydl.params)
            with patch.object(fd, "report_error") as report:
                self.assertFalse(fd.real_download("out.mp4", {"url": "https://cdn.test/a.m3u8"}))
        report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
