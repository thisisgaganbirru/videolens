import io
import json
import socket
import unittest
from unittest.mock import MagicMock, patch

from app.domain.errors import MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.media import captions
from app.infrastructure.media.captions import (
    _fetch_track,
    _pick_format,
    _pick_track,
    parse_caption_payload,
)

_ADDRESSES = {"cdn.test": "93.184.216.34", "x.test": "93.184.216.34", "meta.test": "169.254.169.254"}


def _resolve(host, port, *args, **kwargs):
    """A fake DNS: public names answer a public address, `meta.test` the
    cloud metadata one."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_ADDRESSES[host], port))]


class _FakeSocket:
    """Enough of a socket for http.client: swallows the request and replays
    one canned HTTP response."""

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

VTT = """WEBVTT
Kind: captions
Language: en

1
00:00:01.000 --> 00:00:04.000
hello <c.colorE5E5E5>there</c> world

2
00:00:04.000 --> 00:00:06.000
hello there world

3
00:00:06.000 --> 00:00:09.000
second &amp; line
"""


class ParseCaptionPayloadTests(unittest.TestCase):
    def test_strips_vtt_scaffolding_and_cue_tags(self) -> None:
        self.assertEqual(parse_caption_payload(VTT, "vtt"), "hello there world\nsecond & line")

    def test_collapses_the_rolling_duplicate_lines_auto_captions_emit(self) -> None:
        # Auto-captions repeat the previous line as the window scrolls; kept
        # verbatim it would triple the token cost and read as a stutter.
        payload = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\na b\n\n00:00:02.000 --> 00:00:03.000\na b\n"
        self.assertEqual(parse_caption_payload(payload, "vtt"), "a b")

    def test_parses_srt_numbering_the_same_way(self) -> None:
        payload = "1\n00:00:01,000 --> 00:00:02,000\nfirst\n\n2\n00:00:02,000 --> 00:00:03,000\nsecond\n"
        self.assertEqual(parse_caption_payload(payload, "srt"), "first\nsecond")

    def test_parses_json3_segments(self) -> None:
        payload = json.dumps(
            {"events": [{"segs": [{"utf8": "foo "}, {"utf8": "bar"}]}, {"segs": [{"utf8": "\n"}]}, {"segs": [{"utf8": "baz"}]}]}
        )
        self.assertEqual(parse_caption_payload(payload, "json3"), "foo bar\nbaz")

    def test_parses_xml_transcript_formats_and_unescapes_entities(self) -> None:
        payload = '<transcript><text start="1">a &amp; b</text><text start="2">c</text></transcript>'
        self.assertEqual(parse_caption_payload(payload, "srv1"), "a & b\nc")

    def test_an_empty_track_parses_to_an_empty_string(self) -> None:
        self.assertEqual(parse_caption_payload("WEBVTT\n\n", "vtt"), "")


class TrackSelectionTests(unittest.TestCase):
    def test_prefers_publisher_subtitles_over_machine_captions(self) -> None:
        info = {
            "subtitles": {"en": [{"ext": "vtt", "url": "u1"}]},
            "automatic_captions": {"en": [{"ext": "vtt", "url": "u2"}]},
        }
        language, formats, automatic = _pick_track(info)

        self.assertEqual(language, "en")
        self.assertFalse(automatic)
        self.assertEqual(formats[0]["url"], "u1")

    def test_falls_back_to_automatic_captions(self) -> None:
        info = {"subtitles": {}, "automatic_captions": {"en": [{"ext": "vtt", "url": "u2"}]}}
        _, _, automatic = _pick_track(info)

        self.assertTrue(automatic)

    def test_takes_any_language_when_no_preferred_one_exists(self) -> None:
        # Some transcript beats none, even in a language we did not ask for.
        info = {"subtitles": {"ja": [{"ext": "vtt", "url": "u"}]}, "automatic_captions": {}}
        language, _, _ = _pick_track(info)

        self.assertEqual(language, "ja")

    def test_returns_none_when_there_are_no_tracks_at_all(self) -> None:
        self.assertIsNone(_pick_track({"subtitles": {}, "automatic_captions": {}}))
        self.assertIsNone(_pick_track({}))

    def test_prefers_the_format_that_needs_the_least_parsing(self) -> None:
        formats = [{"ext": "srt", "url": "a"}, {"ext": "json3", "url": "b"}, {"ext": "vtt", "url": "c"}]

        self.assertEqual(_pick_format(formats)["ext"], "json3")

    def test_accepts_an_unranked_format_rather_than_giving_up(self) -> None:
        self.assertEqual(_pick_format([{"ext": "weird", "url": "a"}])["ext"], "weird")

    def test_ignores_formats_with_no_url(self) -> None:
        self.assertIsNone(_pick_format([{"ext": "vtt"}]))


if __name__ == "__main__":
    unittest.main()

@patch("app.infrastructure.media.net.socket.getaddrinfo", side_effect=_resolve)
class CaptionTrackFetchTests(unittest.TestCase):
    """The track URL comes from the fetched page, so it gets the same guard as
    the submitted one: checked, pinned, redirects re-checked, size capped."""

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_refuses_a_link_local_track_without_connecting(self, connect, _dns) -> None:
        with self.assertRaisesRegex(MediaValidationError, "private network"):
            _fetch_track("http://meta.test/latest/meta-data/iam/", None)
        connect.assert_not_called()

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_refuses_loopback_and_private_literals(self, connect, _dns) -> None:
        for url in ("http://127.0.0.1/x.vtt", "http://10.0.0.5/x.vtt", "http://[::1]/x.vtt"):
            with self.assertRaisesRegex(MediaValidationError, "private network", msg=url):
                with patch(
                    "app.infrastructure.media.net.socket.getaddrinfo",
                    return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (url.split("/")[2].strip("[]"), 80))],
                ):
                    _fetch_track(url, None)
        connect.assert_not_called()

    def test_only_http_and_https(self, _dns) -> None:
        for url in ("file:///etc/passwd", "ftp://cdn.test/x.vtt", "gopher://cdn.test/"):
            with self.assertRaises(MediaValidationError, msg=url):
                _fetch_track(url, None)

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_refuses_a_redirect_to_a_private_address(self, connect, _dns) -> None:
        connect.return_value = _FakeSocket(
            _response("302 Found", {"Location": "http://meta.test/latest/", "Content-Length": "0"})
        )

        with self.assertRaisesRegex(MediaValidationError, "private network"):
            _fetch_track("http://cdn.test/en.vtt", None)
        # Only the public first hop was ever dialled, at its approved address.
        connect.assert_called_once()
        self.assertEqual(connect.call_args.args[0], ("93.184.216.34", 80))

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_returns_a_track_under_the_cap(self, connect, _dns) -> None:
        body = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n"
        connect.return_value = _FakeSocket(
            _response("200 OK", {"Content-Length": str(len(body))}, body)
        )

        self.assertEqual(_fetch_track("http://cdn.test/en.vtt", "UA"), body.decode())

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_a_body_over_the_cap_fails_even_without_content_length(self, connect, _dns) -> None:
        connect.return_value = _FakeSocket(
            _response("200 OK", {"Connection": "close"}, b"x" * 64)
        )

        with patch.object(captions, "MAX_CAPTION_BYTES", 32), patch.object(
            captions, "_READ_CHUNK_BYTES", 8
        ), self.assertRaisesRegex(ValueError, "over the cap"):
            _fetch_track("http://cdn.test/en.vtt", None)

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_a_declared_size_over_the_cap_fails_before_reading(self, connect, _dns) -> None:
        connect.return_value = _FakeSocket(
            _response("200 OK", {"Content-Length": str(captions.MAX_CAPTION_BYTES + 1)})
        )

        with self.assertRaisesRegex(ValueError, "declares"):
            _fetch_track("http://cdn.test/en.vtt", None)


@patch("app.infrastructure.media.net.socket.getaddrinfo", side_effect=_resolve)
class CaptionSalvageSsrfTests(unittest.IsolatedAsyncioTestCase):
    """The reviewed attack end to end: a public page whose `<track>` points at
    the metadata service. The salvage path must come back empty, not with the
    metadata body as a transcript."""

    @patch("app.infrastructure.media.net.socket.create_connection")
    async def test_a_page_track_pointing_inside_is_not_fetched(self, connect, _dns) -> None:
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.__exit__.return_value = False
        downloader.params = {"http_headers": {"User-Agent": "UA"}}
        downloader.extract_info.return_value = {
            "duration": 10,
            "subtitles": {"en": [{"ext": "vtt", "url": "http://meta.test/latest/meta-data/"}]},
        }
        with patch.object(captions, "GuardedYoutubeDL", return_value=downloader):
            result = await captions.fetch_captions(Settings(), "https://x.test/p")

        self.assertIsNone(result)
        connect.assert_not_called()
