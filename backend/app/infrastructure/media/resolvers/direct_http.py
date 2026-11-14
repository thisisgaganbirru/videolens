"""A plain HTTP GET for URLs that already point straight at a media file.

This exists as a fallback for the case where yt-dlp declines a link it should
have handled - an unrecognized host, an odd content type, a broken extractor.
Those links are just files on a web server, and fetching one needs none of
yt-dlp's machinery.

Written against the standard library on purpose: the alternative is taking a
direct dependency on a package that is currently only present transitively,
which would mean re-pinning the hash-locked requirements for a fallback path.
"""

import asyncio
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

from ....domain.entities import SavedUpload
from ....domain.entitlements import MediaLimits, size_over_limit_message
from ....domain.errors import MediaValidationError
from ...config import Settings
from ..limits import effective_limits
from ..net import ValidatingRedirectHandler, build_public_opener, validate_public_url
from ..uploads import _cleanup_dir, create_run_dir

_TIMEOUT_SECONDS = 30
_CHUNK_SIZE = 1024 * 1024
_USER_AGENT = "VideoLens/1.0 (+https://github.com/thisisgaganbirru/videolens)"


# Kept under its old name: the handler moved to net.py so the thumbnail
# fetch shares the one copy.
_ValidatingRedirectHandler = ValidatingRedirectHandler


def _size_of(path: str) -> int | None:
    try:
        return os.path.getsize(path)
    except OSError:
        return None


class DirectHttpResolver:
    """SourceResolver for URLs whose path already names a supported media file."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "direct-http"

    def can_handle(self, url: str) -> bool:
        try:
            path = urlparse(url).path.lower()
        except ValueError:
            return False
        return any(path.endswith(extension) for extension in self._settings.allowed_extensions)

    async def fetch(self, run_id: str, url: str, limits: MediaLimits | None = None) -> SavedUpload:
        limits = effective_limits(self._settings, limits)
        await asyncio.to_thread(validate_public_url, url)
        run_dir = create_run_dir(self._settings, run_id)
        try:
            path = await asyncio.to_thread(self._download, url, run_dir, limits)
        except MediaValidationError:
            _cleanup_dir(run_dir)
            raise
        except Exception as exc:  # noqa: BLE001 - urllib errors name internal hosts
            _cleanup_dir(run_dir)
            raise MediaValidationError(
                "This link couldn't be downloaded.",
                log_detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        # No metadata: a bare file on a web server carries no publisher
        # information, which is exactly why this is the fallback and not the
        # primary path.
        return SavedUpload(path=path, run_dir=run_dir, size_bytes=_size_of(path))

    def _download(self, url: str, run_dir: str, limits: MediaLimits | None = None) -> str:
        limits = effective_limits(self._settings, limits)
        max_bytes = limits.max_file_size_bytes
        extension = os.path.splitext(urlparse(url).path)[1].lower()
        destination = os.path.join(run_dir, f"download{extension}")

        # Checks and pins the address on the first request and on every redirect.
        opener = build_public_opener()
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

        try:
            response = opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise MediaValidationError(
                "That link's server refused the download.",
                log_detail=f"HTTP {exc.code} {exc.reason} for {url}",
            ) from exc

        with response:
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise MediaValidationError(size_over_limit_message(limits))

            total = 0
            with open(destination, "wb") as out_file:
                while chunk := response.read(_CHUNK_SIZE):
                    total += len(chunk)
                    if total > max_bytes:
                        raise MediaValidationError(size_over_limit_message(limits))
                    out_file.write(chunk)

        if total == 0:
            raise MediaValidationError("That link returned an empty file.")
        return destination
