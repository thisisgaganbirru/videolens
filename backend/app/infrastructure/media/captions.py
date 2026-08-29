"""Recovers a subtitle track when the media itself cannot be downloaded.

This is the salvage path, not a feature of the happy path. It is reached only
after every resolver has failed, and it exists because those two failures are
not correlated: a platform that refuses to serve video bytes (HTTP 403, format
restrictions, anti-bot checks) will usually still hand over captions. Turning
that into a real transcript is better than turning it into
"Media analysis failed. Please try again."
"""

import asyncio
import html
import json
import re

from yt_dlp import YoutubeDL

from ...domain.entities import CaptionTrack, SourceMetadata
from ..config import Settings
from .net import validate_public_url
from .ytdlp_downloader import _cookie_options, _source_metadata_from_info

# Ordered by how little parsing they need. json3 is YouTube's own structured
# format and needs no timestamp stripping at all.
_PREFERRED_FORMATS = ("json3", "vtt", "srt", "ttml", "srv1")

_PREFERRED_LANGUAGES = ("en", "en-US", "en-GB", "es", "hi")

_TIMESTAMP_LINE = re.compile(r"^\d{1,2}:\d{2}:\d{2}[.,]\d{3}\s*-->")
_CUE_TAG = re.compile(r"<[^>]+>")
_XML_TEXT = re.compile(r"<text[^>]*>(.*?)</text>", re.DOTALL)


def _pick_track(info: dict) -> tuple[str, list[dict], bool] | None:
    """Choose a language and its format list, preferring human-written
    subtitles over machine transcription."""
    for automatic, key in ((False, "subtitles"), (True, "automatic_captions")):
        tracks = info.get(key) or {}
        if not tracks:
            continue
        for language in _PREFERRED_LANGUAGES:
            if tracks.get(language):
                return language, tracks[language], automatic
        # No preferred language available - take whatever the publisher has
        # rather than failing, since some transcript beats none.
        language = next(iter(tracks))
        return language, tracks[language], automatic
    return None


def _pick_format(formats: list[dict]) -> dict | None:
    by_ext = {entry.get("ext"): entry for entry in formats if entry.get("url")}
    for ext in _PREFERRED_FORMATS:
        if ext in by_ext:
            return by_ext[ext]
    return next(iter(by_ext.values()), None)


def _parse_json3(payload: str) -> str:
    events = json.loads(payload).get("events") or []
    lines = []
    for event in events:
        text = "".join(segment.get("utf8", "") for segment in event.get("segs") or [])
        text = text.strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _parse_xml_captions(payload: str) -> str:
    return "\n".join(
        html.unescape(_CUE_TAG.sub("", match)).strip()
        for match in _XML_TEXT.findall(payload)
        if match.strip()
    )


def _parse_cue_format(payload: str) -> str:
    """Strip WEBVTT/SRT scaffolding down to the spoken lines, collapsing the
    duplicate rolling-window lines auto-captions are full of."""
    lines: list[str] = []
    for raw in payload.splitlines():
        line = raw.strip()
        if (
            not line
            or line.startswith("WEBVTT")
            or line.startswith("NOTE")
            or line.startswith("Kind:")
            or line.startswith("Language:")
            or line.isdigit()
            or _TIMESTAMP_LINE.match(line)
        ):
            continue
        line = html.unescape(_CUE_TAG.sub("", line)).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)


def parse_caption_payload(payload: str, ext: str) -> str:
    if ext == "json3":
        return _parse_json3(payload)
    if ext in {"srv1", "srv2", "srv3", "ttml"}:
        return _parse_xml_captions(payload)
    return _parse_cue_format(payload)


async def fetch_captions(settings: Settings, url: str) -> CaptionTrack | None:
    """Return the best available transcript for `url`, or None.

    Returns None rather than raising for every expected miss (no captions, an
    unparseable track, a network refusal): the caller is already handling a
    failed download and needs a yes/no, not a second error to reconcile.
    """
    await asyncio.to_thread(validate_public_url, url)

    def run() -> CaptionTrack | None:
        options = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "quiet": True,
            "no_warnings": True,
            "cachedir": False,
            "socket_timeout": 30,
            **_cookie_options(settings),
        }
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)

            duration = info.get("duration")
            if duration and duration > settings.max_duration_seconds:
                # The duration cap is a product policy about how much media we
                # will analyze, not an artefact of downloading it. A caption
                # track must not become a way around it.
                return None

            chosen = _pick_track(info)
            if chosen is None:
                return None
            language, formats, automatic = chosen
            track = _pick_format(formats)
            if track is None:
                return None

            payload = downloader.urlopen(track["url"]).read().decode("utf-8", errors="ignore")

        text = parse_caption_payload(payload, track.get("ext", ""))
        if not text.strip():
            return None
        return CaptionTrack(
            text=text,
            language=language,
            automatic=automatic,
            metadata=_source_metadata_from_info(info, url),
        )

    try:
        return await asyncio.to_thread(run)
    except Exception:  # noqa: BLE001 - every miss here is expected, not exceptional
        return None
