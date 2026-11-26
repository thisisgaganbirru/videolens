import os
import shutil

from ...domain.entities import MediaSlide, SlideKind
from ...domain.entitlements import MediaLimits, clock, duration_over_limit_message
from ...domain.errors import MediaValidationError
from ..config import Settings
from .limits import effective_limits
from .process import run_process
from .uploads import cleanup_run_dir

# ffprobe reads a header and a few packets: seconds even for a large file.
# Generous, since the API runs it on every upload.
FFPROBE_TIMEOUT_SECONDS = 30
# The re-encode. Under WORKER_LONG_JOB_TIMEOUT_SECONDS' default (1800 s);
# a standard job is cancelled at its own timeout first, which kills it too.
NORMALIZE_TIMEOUT_SECONDS = 1200

# Every probe and encode reads one local file and nothing else. ffmpeg picks
# the demuxer from the content, not the extension, so a playlist named .mp4
# (HLS, DASH, ffconcat) would otherwise be free to open the URLs it lists;
# the whitelist is inherited by every nested open, so it cannot.
INPUT_PROTOCOLS = ["-protocol_whitelist", "file"]

# How text begins: markup (`<`: XML, a DASH or IMF manifest, SMIL, in any
# case and after any comment) or a playlist directive (`#`: HLS). No accepted
# container (.mp3 opens with `ID3` or an 0xFF frame sync, .mp4/.mov with a
# box size and type) starts with either, so a file whose first non-blank
# byte is one of them is refused before ffprobe sees it. `ffconcat` is the
# one text signature that is neither.
_TEXT_STARTS = (b"<", b"#", b"ffconcat")
_WHITESPACE = b" \t\r\n\x0b\x0c"
_SNIFF_BYTES = 64
# Box types an MP4/MOV file opens with (ISO BMFF / QuickTime top level).
_TOP_LEVEL_BOXES = frozenset({b"ftyp", b"mdat", b"moov", b"free", b"skip", b"wide", b"pnot", b"uuid", b"styp"})
# Demuxers that open other files or URLs that the input names. ffprobe
# reports the one it used as `format_name` (a comma list for a family); any
# of these is refused even if the content check above missed the file. The
# whitelist already stops anything but local files.
_PLAYLIST_DEMUXERS = frozenset({
    "hls", "applehttp", "dash", "webm_dash_manifest", "concat", "ffconcat", "imf", "smil", "sdp", "rtp", "rtsp",
})

# Image slides of a multi-slide post. They must decode as one of these (the
# downloader only sniffed their first bytes), and are re-encoded to a JPEG
# whose longest side is at most MAX_SLIDE_IMAGE_SIDE: Gemini tiles a large
# image into 768 px squares, so this keeps a dense infographic legible
# without paying for pixels no post has (Instagram's largest are 1440 px).
_IMAGE_SLIDE_CODECS = frozenset({"mjpeg", "png", "webp"})
MAX_SLIDE_IMAGE_SIDE = 2048
_UNREADABLE_SLIDE = "A slide in this post couldn't be read."


def _media_binary(settings: Settings, name: str) -> str:
    configured = settings.ffmpeg_location.strip()
    executable = f"{name}.exe" if os.name == "nt" else name

    if configured:
        location = os.path.abspath(os.path.expanduser(configured))
        directory = location if os.path.isdir(location) else os.path.dirname(location)
        candidate = os.path.join(directory, executable)
        if os.path.isfile(candidate):
            return candidate
        raise MediaValidationError(
            "This file couldn't be processed.",
            log_detail=f"{name} was not found in the configured FFMPEG_LOCATION directory.",
        )

    discovered = shutil.which(name)
    if discovered:
        return discovered
    raise MediaValidationError(
        "This file couldn't be processed.",
        log_detail=(
            f"{name} is not on PATH and FFMPEG_LOCATION is unset. Install FFmpeg or "
            "set FFMPEG_LOCATION."
        ),
    )


def validate_media_tools(settings: Settings) -> None:
    _media_binary(settings, "ffmpeg")
    _media_binary(settings, "ffprobe")


def _clock(seconds: float) -> str:
    """`m:ss`. Kept under its old name; the formatter lives in the domain now
    so the over-limit messages share it (`domain/entitlements.py`)."""
    return clock(seconds)


def _refuse_playlist(path: str) -> None:
    """A cheap content check ahead of ffprobe: text that opens like a
    playlist or a manifest is not media, whatever its name says."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(_SNIFF_BYTES)
    except OSError:
        return  # ffprobe reports an unreadable file in its own words
    head = head.removeprefix(b"\xef\xbb\xbf")  # a UTF-8 BOM
    text = head.lstrip(_WHITESPACE)
    if not text.startswith(_TEXT_STARTS):
        return
    if len(text) != len(head) and head[4:8] in _TOP_LEVEL_BOXES:
        # The "whitespace" was the first byte of an MP4/MOV box size (a
        # first `mdat` over ~150 MB), not text: bytes 4-8 are its box type.
        return
    raise MediaValidationError(
        "This file couldn't be read. It may be corrupted or in a format we don't support.",
        log_detail=f"refused before ffprobe: the content is a playlist or manifest ({text[:12]!r})",
    )


def _refuse_playlist_demuxer(format_name: str) -> None:
    used = {name.strip().lower() for name in format_name.split(",")}
    if used & _PLAYLIST_DEMUXERS or any("dash" in name for name in used):
        raise MediaValidationError(
            "This file couldn't be read. It may be corrupted or in a format we don't support.",
            log_detail=f"refused after ffprobe: it was opened as a playlist or manifest ({format_name[:40]!r})",
        )


def _probe_fields(stdout: bytes) -> dict[str, str]:
    fields = {}
    for line in stdout.decode(errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


async def probe_duration_seconds(settings: Settings, path: str) -> float:
    _refuse_playlist(path)
    try:
        returncode, stdout, stderr = await run_process(
            [
                _media_binary(settings, "ffprobe"),
                "-v", "error",
                *INPUT_PROTOCOLS,
                "-show_entries", "format=format_name,duration",
                "-of", "default=noprint_wrappers=1",
                path,
            ],
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise MediaValidationError(
            "This file couldn't be read. It may be corrupted or in a format we don't support.",
            log_detail=f"ffprobe timed out after {FFPROBE_TIMEOUT_SECONDS}s",
        ) from exc
    fields = _probe_fields(stdout) if returncode == 0 else {}
    if returncode == 0:
        # Before the duration check, so a manifest whose segments did not
        # open (no duration) is still logged as what it is.
        _refuse_playlist_demuxer(fields.get("format_name", ""))
    if returncode != 0 or not fields.get("duration"):
        raise MediaValidationError(
            "This file couldn't be read. It may be corrupted or in a format we don't support.",
            log_detail=(
                f"ffprobe exited {returncode}: "
                + stderr.decode(errors="ignore")[-500:]
            ),
        )
    try:
        return float(fields["duration"])
    except ValueError as exc:
        raise MediaValidationError(
            "This file couldn't be read. It may be corrupted or in a format we don't support.",
            log_detail=f"ffprobe returned an unparseable duration: {stdout!r}",
        ) from exc


async def enforce_duration_cap(
    settings: Settings, run_id: str, path: str, limits: MediaLimits | None = None
) -> float:
    limits = effective_limits(settings, limits)
    try:
        duration = await probe_duration_seconds(settings, path)
    except MediaValidationError:
        cleanup_run_dir(settings, run_id)
        raise
    if duration > limits.max_duration_seconds:
        cleanup_run_dir(settings, run_id)
        raise MediaValidationError(duration_over_limit_message(duration, limits))
    return duration


async def probe_image(settings: Settings, path: str) -> None:
    """Refuse an image slide that is not really a JPEG, PNG or WebP image."""
    _refuse_playlist(path)
    try:
        returncode, stdout, stderr = await run_process(
            [
                _media_binary(settings, "ffprobe"),
                "-v", "error",
                *INPUT_PROTOCOLS,
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name:format=format_name",
                "-of", "default=noprint_wrappers=1",
                path,
            ],
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise MediaValidationError(
            _UNREADABLE_SLIDE, log_detail=f"ffprobe (image slide) timed out after {FFPROBE_TIMEOUT_SECONDS}s"
        ) from exc
    fields = _probe_fields(stdout) if returncode == 0 else {}
    if returncode == 0:
        _refuse_playlist_demuxer(fields.get("format_name", ""))
    if returncode != 0 or fields.get("codec_name") not in _IMAGE_SLIDE_CODECS:
        raise MediaValidationError(
            _UNREADABLE_SLIDE,
            log_detail=(
                f"image slide: ffprobe exited {returncode}, codec {fields.get('codec_name')!r}: "
                + stderr.decode(errors="ignore")[-300:]
            ),
        )


async def enforce_slides_cap(
    settings: Settings, run_id: str, slides: tuple[MediaSlide, ...], limits: MediaLimits | None = None
) -> float:
    """`enforce_duration_cap` for a multi-slide post: every slide is probed,
    and the video slides' lengths count against the cap together (images
    take no time). Returns that total."""
    limits = effective_limits(settings, limits)
    total = 0.0
    try:
        for slide in slides:
            if slide.kind is SlideKind.IMAGE:
                await probe_image(settings, slide.path)
            else:
                total += await probe_duration_seconds(settings, slide.path)
    except MediaValidationError:
        cleanup_run_dir(settings, run_id)
        raise
    if total > limits.max_duration_seconds:
        cleanup_run_dir(settings, run_id)
        raise MediaValidationError(
            duration_over_limit_message(total, limits, lead="The videos in this post are")
        )
    return total


async def _has_video_stream(settings: Settings, path: str) -> bool:
    try:
        returncode, stdout, _ = await run_process(
            [
                _media_binary(settings, "ffprobe"),
                "-v", "error",
                *INPUT_PROTOCOLS,
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                path,
            ],
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise MediaValidationError(
            "This file couldn't be processed.",
            log_detail=f"ffprobe (stream check) timed out after {FFPROBE_TIMEOUT_SECONDS}s",
        ) from exc
    return returncode == 0 and _first_csv_field(stdout) == b"video"


def _first_csv_field(stdout: bytes) -> bytes:
    """ffprobe's csv writer appends a trailing comma (and can add further
    lines) when the stream carries side data - a phone video's rotation
    matrix, or the ambient-viewing block on Instagram's VP9 reels - so the
    output is `video,` rather than `video`. Comparing the whole output sent
    those files down the audio-only path, which drops the picture with `-vn`
    and fails outright when there is no audio track either."""
    lines = stdout.strip().splitlines()
    return lines[0].split(b",")[0].strip() if lines else b""


async def normalize_media(settings: Settings, src_path: str, run_dir: str, *, name: str = "normalized") -> str:
    # `name`: the output's stem, so a post's slides do not overwrite each other.
    if await _has_video_stream(settings, src_path):
        normalized_path = os.path.join(run_dir, f"{name}.mp4")
        command = [
            _media_binary(settings, "ffmpeg"), "-y", *INPUT_PROTOCOLS, "-i", src_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart", normalized_path,
        ]
    else:
        normalized_path = os.path.join(run_dir, f"{name}.mp3")
        command = [
            _media_binary(settings, "ffmpeg"), "-y", *INPUT_PROTOCOLS, "-i", src_path,
            "-vn", "-c:a", "libmp3lame", "-b:a", "192k", normalized_path,
        ]

    try:
        returncode, _, stderr = await run_process(command, timeout=NORMALIZE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise MediaValidationError(
            "This file couldn't be processed.",
            log_detail=f"ffmpeg timed out after {NORMALIZE_TIMEOUT_SECONDS}s",
        ) from exc
    if returncode != 0:
        raise MediaValidationError(
            "This file couldn't be processed.",
            log_detail=(
                f"ffmpeg exited {returncode}: "
                + stderr.decode(errors="ignore")[-2000:]
            ),
        )
    return normalized_path


async def normalize_image(settings: Settings, src_path: str, dest_path: str) -> str:
    """One image slide as a JPEG no larger than MAX_SLIDE_IMAGE_SIDE on its
    longest side (never enlarged). Re-encoding also drops the source's
    metadata, so nothing but pixels reaches Gemini."""
    side = MAX_SLIDE_IMAGE_SIDE
    command = [
        _media_binary(settings, "ffmpeg"), "-y", *INPUT_PROTOCOLS, "-i", src_path,
        "-frames:v", "1",
        "-vf", f"scale='min({side},iw)':'min({side},ih)':force_original_aspect_ratio=decrease",
        "-map_metadata", "-1", "-q:v", "2", dest_path,
    ]
    try:
        returncode, _, stderr = await run_process(command, timeout=FFPROBE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise MediaValidationError(
            _UNREADABLE_SLIDE, log_detail=f"ffmpeg (image slide) timed out after {FFPROBE_TIMEOUT_SECONDS}s"
        ) from exc
    if returncode != 0 or not os.path.isfile(dest_path):
        raise MediaValidationError(
            _UNREADABLE_SLIDE,
            log_detail=f"ffmpeg (image slide) exited {returncode}: " + stderr.decode(errors="ignore")[-1000:],
        )
    return dest_path


async def normalize_slides(
    settings: Settings, slides: tuple[MediaSlide, ...], run_dir: str
) -> tuple[MediaSlide, ...]:
    """Every slide of a post, in order: video slides through `normalize_media`,
    image slides through `normalize_image`."""
    normalized: list[MediaSlide] = []
    for index, slide in enumerate(slides, start=1):
        stem = f"normalized-{index:02d}"
        if slide.kind is SlideKind.IMAGE:
            path = await normalize_image(settings, slide.path, os.path.join(run_dir, f"{stem}.jpg"))
        else:
            path = await normalize_media(settings, slide.path, run_dir, name=stem)
        normalized.append(MediaSlide(path=path, kind=slide.kind))
    return tuple(normalized)
