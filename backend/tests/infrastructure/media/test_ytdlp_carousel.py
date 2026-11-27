"""Multi-slide posts (Instagram carousels) through the real yt-dlp pipeline.

Only the extractor is faked: `extract_info` hands yt-dlp's own
`process_ie_result` the info dict Instagram's extractor builds for a carousel
(`_type: playlist`, one entry per slide, image slides with no formats), so the
output template, the match filter, the progress hook and the guarded image
fetch all run for real against a local HTTP server. The SSRF guard is opened
to loopback for these tests only.
"""

import copy
import http.server
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.domain.entities import SlideKind
from app.domain.entitlements import MediaLimits, MediaTier
from app.domain.errors import MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.media import ytdlp_downloader
from app.infrastructure.media.ytdlp_downloader import download_url
from app.infrastructure.media.ytdlp_net import GuardedYoutubeDL

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 2000
VIDEO = b"fake video bytes " * 200

_PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


class _Handler(http.server.BaseHTTPRequestHandler):
    files: dict[str, bytes] = {}
    seen: list[tuple[str, str | None]] = []

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        type(self).seen.append((self.path, self.headers.get("Referer")))
        body = type(self).files.get(self.path)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


class CarouselDownloadTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        _Handler.files = {"/a.mp4": VIDEO, "/b.mp4": VIDEO, "/big.jpg": JPEG, "/small.jpg": JPEG[:500]}
        _Handler.seen = []
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(temp_dir=self.temp.name, ytdlp_cookies_file="", ytdlp_cookies_from_browser="")
        self.options_seen: list[dict] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    # ------------------------------------------------------------ fixtures

    def _common(self) -> dict:
        return {
            "extractor": "Instagram",
            "extractor_key": "Instagram",
            "webpage_url": "https://www.instagram.com/p/POST/",
            "uploader": "maker",
            "description": "Five things about pasta",
            "http_headers": {"Referer": "https://www.instagram.com/"},
        }

    def _video(self, media_id: str, path: str) -> dict:
        return {
            **self._common(),
            "id": media_id,
            "duration": 4.0,
            "formats": [{"url": f"{self.base}{path}", "format_id": "0", "ext": "mp4", "width": 720, "height": 1280}],
            "thumbnails": [{"url": f"{self.base}/cover-{media_id}.jpg", "width": 720, "height": 1280}],
        }

    def _image(self, media_id: str) -> dict:
        return {
            **self._common(),
            "id": media_id,
            "formats": [],
            "thumbnails": [
                {"url": f"{self.base}/small.jpg", "width": 150, "height": 150},
                {"url": f"{self.base}/big.jpg", "width": 1080, "height": 1350},
            ],
        }

    def _post(self, *entries: dict) -> dict:
        return {**self._common(), "_type": "playlist", "id": "POST", "title": "Post by maker", "entries": list(entries)}

    async def _download(self, ie_result: dict, url: str = "https://www.instagram.com/p/POST/", limits=None):
        test = self

        class FakeExtractor(GuardedYoutubeDL):
            def __init__(self, params=None, *args, **kwargs) -> None:
                test.options_seen.append(dict(params or {}))
                super().__init__(params, *args, **kwargs)

            def extract_info(self, url, download=True, *args, **kwargs):
                return self.process_ie_result(copy.deepcopy(ie_result), download=download)

        # The submitted link itself is checked up front by name (patched, as in
        # the other downloader tests); every fetch yt-dlp then makes goes to
        # 127.0.0.1 through the real guard, opened to loopback. No slide here
        # needs FFmpeg (one format each, nothing to merge), so its lookup is
        # faked too, as in the other downloader tests: CI has no FFmpeg.
        with patch.object(ytdlp_downloader, "validate_public_url"), patch.object(
            ytdlp_downloader, "_media_binary", return_value="/usr/bin/ffmpeg"
        ), patch(
            "app.infrastructure.media.net.is_public_address", return_value=True
        ), patch.dict(
            os.environ, {name: "" for name in _PROXY_VARIABLES}
        ), patch.object(ytdlp_downloader, "GuardedYoutubeDL", FakeExtractor):
            return await download_url(self.settings, "run-c", url, limits)

    # --------------------------------------------------------------- tests

    async def test_mixed_carousel_keeps_every_slide_in_order(self) -> None:
        saved = await self._download(
            self._post(self._video("v1", "/a.mp4"), self._image("i2"), self._video("v3", "/b.mp4"))
        )

        self.assertEqual([slide.kind for slide in saved.slides], [SlideKind.VIDEO, SlideKind.IMAGE, SlideKind.VIDEO])
        self.assertEqual(
            [os.path.basename(slide.path) for slide in saved.slides], ["slide-01.mp4", "slide-02.jpg", "slide-03.mp4"]
        )
        for slide in saved.slides:
            self.assertTrue(os.path.isfile(slide.path))
        with open(saved.slides[1].path, "rb") as fh:
            self.assertEqual(fh.read(), JPEG)
        self.assertEqual(saved.path, saved.slides[0].path)
        self.assertEqual(saved.size_bytes, 2 * len(VIDEO) + len(JPEG))
        # The post's own metadata, and the first slide's poster hints.
        self.assertEqual(saved.metadata.title, "Post by maker")
        self.assertEqual(saved.metadata.description, "Five things about pasta")
        self.assertEqual(saved.thumbnail_urls[0], f"{self.base}/cover-v1.jpg")
        # The largest rendition, fetched with the entry's own headers.
        self.assertIn(("/big.jpg", "https://www.instagram.com/"), _Handler.seen)
        self.assertNotIn("/small.jpg", [path for path, _ in _Handler.seen])

    async def test_single_photo_post_is_one_image_slide(self) -> None:
        saved = await self._download({**self._image("PHOTO"), "title": "Post by maker"})

        self.assertEqual(len(saved.slides), 1)
        self.assertIs(saved.slides[0].kind, SlideKind.IMAGE)
        self.assertEqual(os.path.basename(saved.path), "slide-01.jpg")
        self.assertEqual(saved.size_bytes, len(JPEG))

    async def test_a_one_video_post_stays_on_the_single_file_path(self) -> None:
        saved = await self._download(self._post(self._video("v1", "/a.mp4")))

        self.assertEqual(saved.slides, ())
        self.assertTrue(os.path.isfile(saved.path))
        self.assertEqual(saved.size_bytes, len(VIDEO))

    async def test_a_single_video_keeps_its_old_file_name(self) -> None:
        saved = await self._download(self._video("REEL", "/a.mp4"), url="https://www.instagram.com/reel/REEL/")

        self.assertEqual(saved.slides, ())
        self.assertEqual(os.path.basename(saved.path), "download.mp4")

    async def test_image_bytes_that_are_not_an_image_fail_the_run(self) -> None:
        _Handler.files["/big.jpg"] = b"<html>login</html>"

        with self.assertRaises(MediaValidationError) as caught:
            await self._download(self._post(self._video("v1", "/a.mp4"), self._image("i2")))

        self.assertEqual(str(caught.exception), "A slide in this post couldn't be read.")
        self.assertIn("not JPEG, PNG or WebP", caught.exception.log_detail)
        # The run directory goes with the failure.
        self.assertEqual(os.listdir(self.temp.name), [])

    async def test_the_size_cap_covers_the_whole_post(self) -> None:
        megabyte = 1024 * 1024
        _Handler.files["/a.mp4"] = b"v" * (megabyte - 1000)
        _Handler.files["/big.jpg"] = b"\xff\xd8\xff" + b"\x00" * 5000
        limits = MediaLimits(tier=MediaTier.STANDARD, max_duration_seconds=180, max_file_size_mb=1)

        with self.assertRaises(MediaValidationError):
            await self._download(self._post(self._video("v1", "/a.mp4"), self._image("i2")), limits=limits)

        # The video fit on its own; the image is what went over.
        self.assertIn(("/big.jpg", "https://www.instagram.com/"), _Handler.seen)
        self.assertEqual(os.listdir(self.temp.name), [])

    async def test_a_post_with_nothing_downloadable_says_so(self) -> None:
        empty = {**self._image("i1"), "thumbnails": []}

        with self.assertRaises(MediaValidationError) as caught:
            await self._download(self._post(empty))

        self.assertEqual(str(caught.exception), "This post has no video or image we could download.")

    async def test_only_instagram_links_let_image_entries_through(self) -> None:
        await self._download(self._video("REEL", "/a.mp4"), url="https://www.instagram.com/reel/REEL/")
        await self._download(self._video("YT", "/a.mp4"), url="https://www.youtube.com/watch?v=YT")

        instagram, youtube = self.options_seen
        self.assertTrue(instagram["ignore_no_formats_error"])
        self.assertIs(instagram["match_filter"], ytdlp_downloader._skip_entries_without_media)
        self.assertNotIn("ignore_no_formats_error", youtube)
        self.assertNotIn("match_filter", youtube)
        self.assertEqual(instagram["playlistend"], ytdlp_downloader.MAX_SLIDES)
        self.assertEqual(youtube["playlistend"], 1)

    async def test_another_sites_playlist_is_refused_after_one_entry(self) -> None:
        # A SoundCloud set: not a post, so never "Slide 1 of N (video)".
        playlist = {**self._post(self._video("t1", "/a.mp4"), self._video("t2", "/b.mp4")), "extractor_key": "SoundcloudSet"}

        with self.assertRaises(MediaValidationError) as caught:
            await self._download(playlist, url="https://soundcloud.com/maker/sets/mix")

        self.assertEqual(
            str(caught.exception), "This link is a playlist or set. Paste a link to one video or track instead."
        )
        self.assertIn("SoundcloudSet returned a playlist of 2 entries", caught.exception.log_detail)
        # Only the first entry was fetched before telling it apart.
        self.assertEqual([path for path, _ in _Handler.seen], ["/a.mp4"])
        self.assertEqual(os.listdir(self.temp.name), [])

    async def test_another_sites_one_entry_playlist_is_just_a_video(self) -> None:
        saved = await self._download(self._post(self._video("v1", "/a.mp4")), url="https://example.com/watch/1")

        self.assertEqual(saved.slides, ())
        self.assertTrue(os.path.isfile(saved.path))
        self.assertEqual(saved.size_bytes, len(VIDEO))

    async def test_another_sites_photo_is_never_fetched_as_a_slide(self) -> None:
        with self.assertRaises(MediaValidationError):
            await self._download(self._post(self._image("i1"), self._image("i2")), url="https://example.com/album/1")

        self.assertNotIn("/big.jpg", [path for path, _ in _Handler.seen])

    async def test_slides_past_the_limit_are_dropped(self) -> None:
        entries = [self._image(f"i{index}") for index in range(1, 24)]

        with patch.object(ytdlp_downloader, "MAX_SLIDES", 3):
            saved = await self._download(self._post(*entries))

        self.assertEqual(len(saved.slides), 3)


class ImageHelperTests(unittest.TestCase):
    def test_image_extension_sniffs_the_bytes(self) -> None:
        self.assertEqual(ytdlp_downloader._image_extension(JPEG), ".jpg")
        self.assertEqual(ytdlp_downloader._image_extension(b"\x89PNG\r\n\x1a\n...."), ".png")
        self.assertEqual(ytdlp_downloader._image_extension(b"RIFF\x00\x00\x00\x00WEBPVP8 "), ".webp")
        self.assertIsNone(ytdlp_downloader._image_extension(b"<html>"))
        self.assertIsNone(ytdlp_downloader._image_extension(b"\x00\x00\x00\x18ftypheic"))

    def test_image_url_prefers_the_largest_rendition(self) -> None:
        entry = {
            "thumbnails": [
                {"url": "https://cdn/1080.jpg", "width": 1080, "height": 1350},
                {"url": "https://cdn/150.jpg", "width": 150, "height": 150},
                {"url": "ftp://cdn/huge.jpg", "width": 9000, "height": 9000},
            ]
        }
        self.assertEqual(ytdlp_downloader._image_url(entry), "https://cdn/1080.jpg")
        self.assertEqual(ytdlp_downloader._image_url({"thumbnail": "https://cdn/t.jpg"}), "https://cdn/t.jpg")
        self.assertIsNone(ytdlp_downloader._image_url({}))

    def test_match_filter_only_skips_entries_with_no_media(self) -> None:
        skip = ytdlp_downloader._skip_entries_without_media
        self.assertIsNone(skip({"url": "https://cdn/v.mp4"}))
        self.assertIsNone(skip({"requested_formats": [{}]}))
        self.assertIsNone(skip({}, incomplete=True))
        self.assertIsNotNone(skip({"id": "image"}))

    def test_instagram_hosts(self) -> None:
        self.assertTrue(ytdlp_downloader._is_instagram("https://www.instagram.com/p/x/"))
        self.assertTrue(ytdlp_downloader._is_instagram("https://instagram.com/p/x/"))
        self.assertFalse(ytdlp_downloader._is_instagram("https://notinstagram.com/p/x/"))
        self.assertFalse(ytdlp_downloader._is_instagram("https://www.youtube.com/watch?v=x"))


if __name__ == "__main__":
    unittest.main()
