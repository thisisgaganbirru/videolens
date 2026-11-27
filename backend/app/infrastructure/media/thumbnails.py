"""Poster thumbnail and display size for a run's history card.

The browser keeps History now (IndexedDB), so the run detail has to hand over
a picture it can show without ever asking the server again. That picture is
small on purpose: a JPEG no larger than `MAX_THUMBNAIL_BYTES`, longest side at
most `MAX_SIDE` pixels, delivered inline as a `data:` URL.

Where it comes from, in order:

1. The publisher's own poster (yt-dlp's `thumbnail`/`thumbnails`), fetched
   through the same SSRF guard as every other outbound request, with a byte
   cap and a short wall-clock deadline on the download pool.
2. A frame from the media file itself (~1s in, or 10% of the way through a
   shorter clip), when there is one and it has a picture.
3. Nothing. Audio has no poster, and a failure here is cosmetic: every public
   function in this module logs and returns None instead of raising, because
   a missing thumbnail must never fail an otherwise healthy run.

A multi-slide post (an Instagram carousel) also gets one small picture per
slide (`build_slide_thumbnails`), made from the slide files already on disk:
a JPEG with its longest side at most `SLIDE_MAX_SIDE` and no larger than
`MAX_SLIDE_THUMBNAIL_BYTES`, the whole set held to
`SLIDE_THUMBNAILS_BUDGET_BYTES` and `SLIDE_THUMBNAILS_DEADLINE_SECONDS`. A
video slide's picture is a frame taken the way the poster's is. These are for
the person's own result and browser History only: never sent to Gemini, and
kept server side only on the run record, for RUN_TTL_SECONDS
(docs/backend/run-processing.md).
"""

import asyncio
import base64
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Iterable, Optional

from ...domain.entities import MediaSlide, SlideKind, SlideVisual

from ..config import Settings
from .deadline import DownloadDeadline, run_download
from .ffmpeg import INPUT_PROTOCOLS, _media_binary
from .net import build_public_opener, validate_public_url
from .process import run_process

logger = logging.getLogger("videolens")

MAX_SIDE = 320
MAX_THUMBNAIL_BYTES = 20 * 1024
MAX_SOURCE_IMAGE_BYTES = 3 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 8
# Wall-clock bound on one poster fetch, connection to last byte (socket
# timeouts are per read). Two fetches at most per run.
FETCH_DEADLINE_SECONDS = 10
_READ_CHUNK_BYTES = 64 * 1024
FFMPEG_TIMEOUT_SECONDS = 15

# mjpeg's -q:v runs 2 (best) to 31 (worst). Stepped rather than bisected: the
# first step fits almost every poster, so the common case is one encode.
QUALITY_STEPS = (4, 7, 11, 16, 23, 31)
# Only reached when even the worst quality at MAX_SIDE is over the ceiling
# (very noisy images). The ceiling is hard, so the picture gets smaller.
SIDE_STEPS = (MAX_SIDE, 240, 180, 120, 80)

# Slide thumbnails: bigger than the poster (they are looked at, not just
# recognised), so a 1080x1350 slide becomes 384x480. q:v 5 puts a typical
# slide at roughly 10-45 KB; the further steps only matter for very noisy
# images, which still end up under the per-slide ceiling.
SLIDE_MAX_SIDE = 480
MAX_SLIDE_THUMBNAIL_BYTES = 80 * 1024
SLIDE_QUALITY_STEPS = (5, 8, 12, 18, 25, 31)
SLIDE_SIDE_STEPS = (SLIDE_MAX_SIDE, 360, 240)
# The whole set rides on the run record (Redis or memory) for RUN_TTL_SECONDS
# and is read back with every `get` of it, so it is capped as a set: once the
# running total (data URLs, in bytes) would pass this, that slide and every
# later one get `thumbnail: null`. 20 slides (the downloader's MAX_SLIDES) at
# ~60 KB fit.
SLIDE_THUMBNAILS_BUDGET_BYTES = 1_200_000
# Wall clock for the whole set, inside describe_visuals' overall timeout
# (service.py) and after the poster, so slow slides only ever cost slides.
SLIDE_THUMBNAILS_DEADLINE_SECONDS = 25

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
    """Run one ffmpeg/ffprobe process with a hard deadline, killed on
    timeout and on cancellation (`process.run_process`, shared with
    ffmpeg.py)."""
    code, stdout, _ = await run_process(command, timeout=FFMPEG_TIMEOUT_SECONDS, stdin=stdin)
    return code, stdout


async def probe_dimensions(settings: Settings, path: str) -> Optional[tuple[int, int]]:
    try:
        code, stdout = await _run(
            [
                _media_binary(settings, "ffprobe"),
                "-v", "error",
                *INPUT_PROTOCOLS,
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


async def encode_thumbnail(
    settings: Settings,
    image: bytes,
    *,
    side_steps: tuple[int, ...] = SIDE_STEPS,
    quality_steps: tuple[int, ...] = QUALITY_STEPS,
    max_bytes: int = MAX_THUMBNAIL_BYTES,
) -> Optional[bytes]:
    """Re-encode any image ffmpeg can read to a JPEG within MAX_SIDE and
    MAX_THUMBNAIL_BYTES (the defaults: the poster's), stepping quality down
    and then size down until it fits. None if it never fits or ffmpeg cannot
    read the input."""
    ffmpeg = _media_binary(settings, "ffmpeg")
    for side in side_steps:
        for quality in quality_steps:
            code, stdout = await _run(
                [
                    # stdin only: the fetched bytes are the publisher's.
                    ffmpeg, "-v", "error", "-protocol_whitelist", "pipe", "-i", "pipe:0",
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
            if len(stdout) <= max_bytes:
                return stdout
    return None


def frame_offset_seconds(duration_seconds: Optional[float]) -> float:
    """~1s in, so a fade from black is usually over; 10% of the way through a
    clip shorter than 10s so the seek never lands past the end."""
    if duration_seconds is None or duration_seconds <= 0:
        return 1.0
    return min(1.0, duration_seconds * 0.1)


async def extract_frame(
    settings: Settings, media_path: str, duration_seconds: Optional[float], *, max_side: int = MAX_SIDE
) -> Optional[bytes]:
    """One frame as a PNG (lossless, already <= `max_side` so it stays small
    in memory). ffmpeg applies the rotation itself, so a portrait clip yields a
    portrait frame. Retries at 0s when the first seek finds nothing."""
    ffmpeg = _media_binary(settings, "ffmpeg")
    for offset in dict.fromkeys((frame_offset_seconds(duration_seconds), 0.0)):
        code, stdout = await _run(
            [
                ffmpeg, "-v", "error",
                "-ss", f"{offset:.3f}", *INPUT_PROTOCOLS, "-i", media_path,
                "-frames:v", "1", "-an",
                "-vf", _scale_filter(max_side),
                "-f", "image2pipe", "-c:v", "png", "pipe:1",
            ]
        )
        if code == 0 and stdout:
            return stdout
    return None


def _fetch_image_sync(deadline: DownloadDeadline, url: str, max_bytes: int, timeout: float) -> bytes:
    validate_public_url(url)
    opener = build_public_opener()
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with opener.open(request, timeout=min(timeout, max(1.0, deadline.remaining))) as response:
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise ValueError(f"thumbnail declares {declared} bytes, over the cap")
        # read1 in chunks, as captions do: a trickling server comes back here
        # to have the deadline checked, and reading one byte past the cap
        # catches an over-size body whatever Content-Length said.
        chunks: list[bytes] = []
        total = 0
        read = getattr(response, "read1", None) or response.read
        while True:
            deadline.check()
            chunk = read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("thumbnail body is over the cap")
            chunks.append(chunk)
        # A deadline that fired mid-read reads as a clean end of file.
        deadline.check()
    if not total:
        raise ValueError("thumbnail body is empty")
    return b"".join(chunks)


async def fetch_image(url: str) -> Optional[bytes]:
    # On the download pool under its own short deadline, like every other
    # outbound fetch: on the default executor a trickling body kept a shared
    # thread busy long after wait_for had stopped waiting for it. The
    # deadline's socket shutdown ends even a read that is already blocked.
    try:
        return await asyncio.wait_for(
            run_download(
                FETCH_DEADLINE_SECONDS,
                _fetch_image_sync,
                url,
                MAX_SOURCE_IMAGE_BYTES,
                FETCH_TIMEOUT_SECONDS,
            ),
            FETCH_DEADLINE_SECONDS + 2,
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


# ------------------------------------------------------------ slide thumbnails


def _read_file(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


async def slide_thumbnail(settings: Settings, slide: MediaSlide) -> Optional[bytes]:
    """One slide's JPEG, or None. An image slide is re-encoded from its file
    (enforce_slides_cap has already probed it as a real JPEG/PNG/WebP); a
    video slide gives the frame the poster would (~1s in, 0s when that finds
    nothing; no per-slide duration is known). A video slide with no picture
    has no frame, so None. Never raises, apart from cancellation."""
    try:
        if slide.kind is SlideKind.IMAGE:
            source = await asyncio.to_thread(_read_file, slide.path)
        else:
            source = await extract_frame(settings, slide.path, None, max_side=SLIDE_MAX_SIDE)
        if not source:
            return None
        return await encode_thumbnail(
            settings,
            source,
            side_steps=SLIDE_SIDE_STEPS,
            quality_steps=SLIDE_QUALITY_STEPS,
            max_bytes=MAX_SLIDE_THUMBNAIL_BYTES,
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - cosmetic, see module docstring
        logger.warning("Slide thumbnail failed", exc_info=True)
        return None


async def build_slide_thumbnails(
    settings: Settings,
    slides: tuple[MediaSlide, ...],
    *,
    budget_bytes: int = SLIDE_THUMBNAILS_BUDGET_BYTES,
    deadline_seconds: float = SLIDE_THUMBNAILS_DEADLINE_SECONDS,
) -> tuple[SlideVisual, ...]:
    """One `SlideVisual` per slide, numbered from 1 in the post's order (the
    numbers the analysis gives `screen_text_segments[].slide`).

    One slide at a time: each is a fraction of a second of FFmpeg, and the
    set runs alongside normalization and Gemini, so there is nothing to gain
    by competing with them. A slide that fails, the slide that would pass the
    byte budget and every one after it, and any slide still unmade at the
    deadline get `thumbnail=None`. Never raises, apart from cancellation."""
    started = time.perf_counter()
    loop = asyncio.get_running_loop()
    give_up_at = loop.time() + deadline_seconds
    thumbs: list[Optional[str]] = [None] * len(slides)
    total = 0
    stopped = ""
    try:
        for index, slide in enumerate(slides):
            remaining = give_up_at - loop.time()
            if remaining <= 0:
                stopped = ", deadline reached"
                break
            try:
                jpeg = await asyncio.wait_for(slide_thumbnail(settings, slide), remaining)
            except asyncio.TimeoutError:
                stopped = ", deadline reached"
                break
            if jpeg is None:
                continue
            data_url = to_data_url(jpeg)
            if total + len(data_url) > budget_bytes:
                stopped = ", over the byte budget"
                break
            total += len(data_url)
            thumbs[index] = data_url
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - cosmetic, see module docstring
        logger.warning("Slide thumbnails failed", exc_info=True)
    logger.debug(
        "Slide thumbnails: %d of %d made, %d bytes, %.2fs%s",
        sum(1 for thumb in thumbs if thumb is not None),
        len(slides),
        total,
        time.perf_counter() - started,
        stopped,
    )
    return tuple(
        SlideVisual(slide=number, kind=slide.kind, thumbnail=thumbs[number - 1])
        for number, slide in enumerate(slides, start=1)
    )
