"""Poster thumbnail and display size for a run's history card.

The browser keeps History now (IndexedDB), so the run detail has to hand over
a picture it can show without ever asking the server again. That picture is
small on purpose: a JPEG no larger than `MAX_THUMBNAIL_BYTES`, longest side at
most `MAX_SIDE` pixels, delivered inline as a `data:` URL.

Where it comes from, in order:

1. The publisher's own poster (yt-dlp's `thumbnail`/`thumbnails`), fetched
   through the same SSRF guard as every other outbound request, with a byte
   cap and a short timeout.
2. A frame from the media file itself (~1s in, or 10% of the way through a
   shorter clip), when there is one and it has a picture.
3. Nothing. Audio has no poster, and a failure here is cosmetic: every public
   function in this module logs and returns None instead of raising, because
   a missing thumbnail must never fail an otherwise healthy run.
"""

import asyncio
import base64
import json
import logging
import urllib.error
import urllib.request
from typing import Iterable, Optional

from ..config import Settings
from .ffmpeg import _media_binary
from .net import build_public_opener, validate_public_url

logger = logging.getLogger("videolens")

MAX_SIDE = 320
MAX_THUMBNAIL_BYTES = 20 * 1024
MAX_SOURCE_IMAGE_BYTES = 3 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 8
FFMPEG_TIMEOUT_SECONDS = 15

# mjpeg's -q:v runs 2 (best) to 31 (worst). Stepped rather than bisected: the
# first step fits almost every poster, so the common case is one encode.
QUALITY_STEPS = (4, 7, 11, 16, 23, 31)
# Only reached when even the worst quality at MAX_SIDE is over the ceiling
# (very noisy images). The ceiling is hard, so the picture gets smaller.
SIDE_STEPS = (MAX_SIDE, 240, 180, 120, 80)

_USER_AGENT = "VideoLens/1.0 (+https://github.com/thisisgaganbirru/videolens)"


def _positive_int(value: object) -> Optional[int]:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def thumbnail_urls_from_info(info: dict) -> tuple[str, ...]:
    """yt-dlp's chosen `thumbnail` first, then the largest entry of
    `thumbnails` as a second try. At most two: a poster is not worth more
    round trips than that."""
    candidates: list[str] = []

    def add(url: object) -> None:
        if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in candidates:
            candidates.append(url)

    add(info.get("thumbnail"))
    entries = [entry for entry in info.get("thumbnails") or [] if isinstance(entry, dict)]

    def rank(entry: dict) -> tuple[int, int]:
        area = (_positive_int(entry.get("width")) or 0) * (_positive_int(entry.get("height")) or 0)
        preference = entry.get("preference")
        return (preference if isinstance(preference, int) else -(10**6), area)

    for entry in sorted(entries, key=rank, reverse=True):
        add(entry.get("url"))
        if len(candidates) >= 2:
            break
    return tuple(candidates[:2])


def dimensions_from_info(info: dict) -> tuple[Optional[int], Optional[int]]:
    width = _positive_int(info.get("width"))
    height = _positive_int(info.get("height"))
    if width is None or height is None:
        return None, None
    return width, height


def parse_video_dimensions(payload: bytes) -> Optional[tuple[int, int]]:
    """Display width/height from `ffprobe -of json` output for stream v:0.

    Rotation is applied: a phone records portrait video as landscape pixels
    plus a 90-degree rotation (the `rotate` tag on older files, a display
    matrix side-data entry on newer ones), and the history card needs the
    shape the person actually saw. An attached picture (MP3 cover art) is not
    a video stream for this purpose - audio has no dimensions.
    """
    try:
        streams = json.loads(payload or b"{}").get("streams") or []
    except (ValueError, AttributeError):
        return None
    if not streams:
        return None
    stream = streams[0]
    if (stream.get("disposition") or {}).get("attached_pic") == 1:
        return None
    width = _positive_int(stream.get("width"))
    height = _positive_int(stream.get("height"))
    if width is None or height is None:
        return None

    rotation: object = (stream.get("tags") or {}).get("rotate")
    for side_data in stream.get("side_data_list") or []:
        if isinstance(side_data, dict) and "rotation" in side_data:
            rotation = side_data["rotation"]
            break
    try:
        degrees = int(round(float(rotation))) if rotation is not None else 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        degrees = 0
    if degrees % 180 != 0 and degrees % 90 == 0:
        width, height = height, width
    return width, height


async def _run(command: list[str], stdin: bytes | None = None) -> tuple[int, bytes]:
    """Run one ffmpeg/ffprobe process with a hard deadline. The process is
    killed on timeout and on cancellation, so a cancelled run never leaves an
    encoder running against a directory that is about to be deleted."""
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(stdin), FFMPEG_TIMEOUT_SECONDS)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    return proc.returncode if proc.returncode is not None else -1, stdout


async def probe_dimensions(settings: Settings, path: str) -> Optional[tuple[int, int]]:
    try:
        code, stdout = await _run(
            [
                _media_binary(settings, "ffprobe"),
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=width,height:stream_disposition=attached_pic"
                ":stream_tags=rotate:stream_side_data=rotation",
                "-of", "json",
                path,
            ]
        )
    except Exception:  # noqa: BLE001 - cosmetic, see module docstring
        logger.warning("Could not probe video dimensions", exc_info=True)
        return None
    if code != 0:
        return None
    return parse_video_dimensions(stdout)


def _scale_filter(side: int) -> str:
    # min() keeps a small image small: the cap shrinks, it never enlarges.
    return f"scale='min({side},iw)':'min({side},ih)':force_original_aspect_ratio=decrease"


async def encode_thumbnail(settings: Settings, image: bytes) -> Optional[bytes]:
    """Re-encode any image ffmpeg can read to a JPEG within MAX_SIDE and
    MAX_THUMBNAIL_BYTES, stepping quality down and then size down until it
    fits. None if it never fits or ffmpeg cannot read the input."""
    ffmpeg = _media_binary(settings, "ffmpeg")
    for side in SIDE_STEPS:
        for quality in QUALITY_STEPS:
            code, stdout = await _run(
                [
                    ffmpeg, "-v", "error", "-i", "pipe:0",
                    "-frames:v", "1",
                    "-vf", _scale_filter(side),
                    "-q:v", str(quality),
                    "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1",
                ],
                stdin=image,
            )
            if code != 0 or not stdout:
                # Unreadable input does not get more readable at a lower
                # quality - stop instead of trying all 30 combinations.
                return None
            if len(stdout) <= MAX_THUMBNAIL_BYTES:
                return stdout
    return None


def frame_offset_seconds(duration_seconds: Optional[float]) -> float:
    """~1s in, so a fade from black is usually over; 10% of the way through a
    clip shorter than 10s so the seek never lands past the end."""
    if duration_seconds is None or duration_seconds <= 0:
        return 1.0
    return min(1.0, duration_seconds * 0.1)


async def extract_frame(
    settings: Settings, media_path: str, duration_seconds: Optional[float]
) -> Optional[bytes]:
    """One frame as a PNG (lossless, already <= MAX_SIDE so it stays small in
    memory). ffmpeg applies the rotation itself, so a portrait clip yields a
    portrait frame. Retries at 0s when the first seek finds nothing."""
    ffmpeg = _media_binary(settings, "ffmpeg")
    for offset in dict.fromkeys((frame_offset_seconds(duration_seconds), 0.0)):
        code, stdout = await _run(
            [
                ffmpeg, "-v", "error",
                "-ss", f"{offset:.3f}", "-i", media_path,
                "-frames:v", "1", "-an",
                "-vf", _scale_filter(MAX_SIDE),
                "-f", "image2pipe", "-c:v", "png", "pipe:1",
            ]
        )
        if code == 0 and stdout:
            return stdout
    return None


def _fetch_image_sync(url: str, max_bytes: int, timeout: float) -> bytes:
    validate_public_url(url)
    opener = build_public_opener()
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with opener.open(request, timeout=timeout) as response:
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise ValueError(f"thumbnail declares {declared} bytes, over the cap")
        # Read one byte past the cap so an over-size body is detectable even
        # when the server omits or lies about Content-Length.
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError("thumbnail body is over the cap")
    if not body:
        raise ValueError("thumbnail body is empty")
    return body


async def fetch_image(url: str) -> Optional[bytes]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _fetch_image_sync, url, MAX_SOURCE_IMAGE_BYTES, FETCH_TIMEOUT_SECONDS
            ),
            FETCH_TIMEOUT_SECONDS + 2,
        )
    except Exception as exc:  # noqa: BLE001 - urllib errors name hosts; log only
        logger.info("Thumbnail fetch failed: %s: %s", type(exc).__name__, exc)
        return None


def to_data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


async def build_thumbnail(
    settings: Settings,
    *,
    thumbnail_urls: Iterable[str] = (),
    media_path: Optional[str] = None,
    has_video: bool = False,
    duration_seconds: Optional[float] = None,
) -> Optional[str]:
    """The fallback order from the module docstring. Never raises."""
    try:
        for url in thumbnail_urls:
            image = await fetch_image(url)
            if image is None:
                continue
            jpeg = await encode_thumbnail(settings, image)
            if jpeg is not None:
                return to_data_url(jpeg)
            logger.info("Fetched thumbnail could not be transcoded; trying the next source")
        if media_path and has_video:
            frame = await extract_frame(settings, media_path, duration_seconds)
            if frame is not None:
                jpeg = await encode_thumbnail(settings, frame)
                if jpeg is not None:
                    return to_data_url(jpeg)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - cosmetic, see module docstring
        logger.warning("Thumbnail capture failed", exc_info=True)
    return None
