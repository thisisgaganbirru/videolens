import json
import unittest

from app.infrastructure.media.captions import (
    _pick_format,
    _pick_track,
    parse_caption_payload,
)

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
