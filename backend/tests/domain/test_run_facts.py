import unittest
from datetime import datetime, timezone

from app.domain.entities import Run, RunStatus, SourceMetadata, VideoAnalysis
from app.domain.run_facts import (
    SNIPPET_MAX_CHARS,
    describe_run,
    file_platform,
    link_platform,
    resolve_orientation,
    resolve_platform,
    resolve_source_kind,
    summary_snippet,
)

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _meta(platform: str, url: str) -> SourceMetadata:
    return SourceMetadata(platform=platform, source_url=url)


def _run(**kwargs) -> Run:
    return Run(
        run_id="r", owner_id="client:o", status=RunStatus.COMPLETE,
        created_at=NOW, updated_at=NOW, **kwargs,
    )


class LinkPlatformTests(unittest.TestCase):
    def test_extractor_keys_fold_into_their_platform(self) -> None:
        cases = {
            "Youtube": "youtube",
            "YoutubeTab": "youtube",
            "Instagram": "instagram",
            "InstagramStory": "instagram",
            "TikTok": "tiktok",
            "Vimeo": "other",
        }
        for key, expected in cases.items():
            with self.subTest(key=key):
                self.assertEqual(link_platform(key, "https://example.com/x"), expected)

    def test_falls_back_to_the_url_host_when_the_extractor_is_unhelpful(self) -> None:
        self.assertEqual(link_platform("Generic", "https://youtu.be/abc"), "youtube")
        self.assertEqual(link_platform(None, "https://www.instagram.com/reel/x/"), "instagram")
        self.assertEqual(link_platform("unknown", "https://vm.tiktok.com/abc"), "tiktok")

    def test_lookalike_hosts_are_not_matched(self) -> None:
        self.assertEqual(link_platform(None, "https://notyoutube.com/watch?v=1"), "other")

    def test_unknown_everything_is_other(self) -> None:
        self.assertEqual(link_platform(None, None), "other")
        self.assertEqual(link_platform("", "not a url"), "other")


class FilePlatformTests(unittest.TestCase):
    def test_mp3_is_audio_everything_else_video(self) -> None:
        self.assertEqual(file_platform(".mp3"), "audio_file")
        self.assertEqual(file_platform(".MP3"), "audio_file")
        self.assertEqual(file_platform("mp3"), "audio_file")
        self.assertEqual(file_platform(".mp4"), "video_file")
        self.assertEqual(file_platform(".mov"), "video_file")
        self.assertEqual(file_platform(None), "video_file")


class SourceKindAndPlatformTests(unittest.TestCase):
    def test_stored_kind_wins(self) -> None:
        self.assertEqual(resolve_source_kind("file", None), "file")
        self.assertEqual(resolve_source_kind("link", None), "link")

    def test_legacy_run_with_metadata_is_a_link(self) -> None:
        self.assertEqual(resolve_source_kind(None, _meta("Youtube", "https://youtube.com/watch?v=1")), "link")

    def test_legacy_run_with_nothing_is_unknown(self) -> None:
        self.assertIsNone(resolve_source_kind(None, None))
        self.assertIsNone(resolve_platform(None, None, None))

    def test_stored_file_platform_is_returned_as_is(self) -> None:
        self.assertEqual(resolve_platform("file", "audio_file", None), "audio_file")

    def test_link_without_metadata_has_no_platform(self) -> None:
        self.assertIsNone(resolve_platform("link", None, None))

    def test_legacy_link_platform_is_inferred_from_metadata(self) -> None:
        self.assertEqual(
            resolve_platform(None, None, _meta("TikTok", "https://www.tiktok.com/@a/video/1")),
            "tiktok",
        )


class OrientationTests(unittest.TestCase):
    def test_youtube_watch_is_landscape(self) -> None:
        self.assertEqual(resolve_orientation("youtube", "https://www.youtube.com/watch?v=abc"), "landscape")
        self.assertEqual(resolve_orientation("youtube", "https://youtu.be/abc"), "landscape")

    def test_youtube_shorts_is_portrait(self) -> None:
        self.assertEqual(resolve_orientation("youtube", "https://youtube.com/shorts/abc"), "portrait")
        self.assertEqual(resolve_orientation("youtube", "https://m.youtube.com/Shorts/abc?si=1"), "portrait")

    def test_other_known_platforms_are_portrait(self) -> None:
        for platform in ("instagram", "tiktok", "other", "audio_file", "video_file"):
            with self.subTest(platform=platform):
                self.assertEqual(resolve_orientation(platform, None), "portrait")

    def test_unknown_is_none(self) -> None:
        self.assertIsNone(resolve_orientation(None, "https://youtube.com/watch?v=1"))
        self.assertIsNone(resolve_orientation("youtube", None))


class SummarySnippetTests(unittest.TestCase):
    def test_short_summary_is_whitespace_collapsed_and_untouched(self) -> None:
        self.assertEqual(summary_snippet("  A  short\n\tsummary. "), "A short summary.")

    def test_empty_is_none(self) -> None:
        self.assertIsNone(summary_snippet(None))
        self.assertIsNone(summary_snippet("   \n "))

    def test_exactly_the_limit_is_not_cut(self) -> None:
        text = "a" * SNIPPET_MAX_CHARS
        self.assertEqual(summary_snippet(text), text)

    def test_long_summary_is_cut_at_a_word_boundary_with_an_ellipsis(self) -> None:
        text = " ".join(["word"] * 100)
        snippet = summary_snippet(text)
        assert snippet is not None
        self.assertLessEqual(len(snippet), SNIPPET_MAX_CHARS)
        self.assertTrue(snippet.endswith("…"))
        self.assertTrue(snippet[:-1].endswith("word"))
        self.assertNotIn("  ", snippet)

    def test_a_single_unbroken_word_is_hard_cut(self) -> None:
        snippet = summary_snippet("x" * 400)
        assert snippet is not None
        self.assertEqual(len(snippet), SNIPPET_MAX_CHARS)
        self.assertTrue(snippet.endswith("…"))

    def test_trailing_punctuation_before_the_ellipsis_is_dropped(self) -> None:
        text = ("alpha, " * 40).strip()
        snippet = summary_snippet(text)
        assert snippet is not None
        self.assertTrue(snippet.endswith("alpha…"))


class DescribeRunTests(unittest.TestCase):
    def test_link_run(self) -> None:
        run = _run(
            source_kind="link",
            duration_seconds=33.0,
            source_metadata=_meta("Youtube", "https://www.youtube.com/watch?v=abc"),
            result=VideoAnalysis(title="T", summary="Sum", transcript="", screen_text="", markdown=""),
        )
        facts = describe_run(run)
        self.assertEqual(facts.source_kind, "link")
        self.assertEqual(facts.platform, "youtube")
        self.assertEqual(facts.orientation, "landscape")
        self.assertEqual(facts.duration_seconds, 33.0)
        self.assertEqual(facts.summary_snippet, "Sum")

    def test_legacy_run_has_all_none(self) -> None:
        facts = describe_run(_run())
        self.assertIsNone(facts.source_kind)
        self.assertIsNone(facts.platform)
        self.assertIsNone(facts.orientation)
        self.assertIsNone(facts.duration_seconds)
        self.assertIsNone(facts.summary_snippet)


class OrientationFromDimensionsTests(unittest.TestCase):
    def test_measured_dimensions_win_over_the_url_heuristic(self) -> None:
        # A YouTube watch URL would say landscape; the file says otherwise.
        self.assertEqual(
            resolve_orientation("youtube", "https://www.youtube.com/watch?v=a", 1080, 1920), "portrait"
        )
        self.assertEqual(resolve_orientation("instagram", None, 1920, 1080), "landscape")

    def test_square_is_portrait(self) -> None:
        self.assertEqual(resolve_orientation("video_file", None, 1080, 1080), "portrait")

    def test_dimensions_work_without_a_platform(self) -> None:
        self.assertEqual(resolve_orientation(None, None, 640, 360), "landscape")

    def test_partial_or_zero_dimensions_fall_back(self) -> None:
        self.assertEqual(resolve_orientation("youtube", "https://youtu.be/a", 1080, None), "landscape")
        self.assertEqual(resolve_orientation("youtube", "https://youtu.be/a", 0, 1920), "landscape")

    def test_describe_run_carries_dimensions(self) -> None:
        facts = describe_run(_run(source_kind="file", platform="video_file", width=1920, height=1080))
        self.assertEqual(facts.orientation, "landscape")
        self.assertEqual((facts.width, facts.height), (1920, 1080))


if __name__ == "__main__":
    unittest.main()
