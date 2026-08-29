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
from ....domain.errors import MediaValidationError
from ...config import Settings
from ..net import validate_public_url
from ..uploads import _cleanup_dir, create_run_dir

_TIMEOUT_SECONDS = 30
_CHUNK_SIZE = 1024 * 1024
_USER_AGENT = "VideoLens/1.0 (+https://github.com/thisisgaganbirru/videolens)"


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-runs the public-address check on every redirect hop.

    Validating only the URL the caller typed is not enough: a public host is
    free to redirect to `http://169.254.169.254/`, and following that blindly
    is the classic way an SSRF guard gets walked straight past.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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

    async def fetch(self, run_id: str, url: str) -> SavedUpload:
        await asyncio.to_thread(validate_public_url, url)
        run_dir = create_run_dir(self._settings, run_id)
        try:
            path = await asyncio.to_thread(self._download, url, run_dir)
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
        return SavedUpload(path=path, run_dir=run_dir)

    def _download(self, url: str, run_dir: str) -> str:
        max_bytes = self._settings.max_file_size_mb * 1024 * 1024
        extension = os.path.splitext(urlparse(url).path)[1].lower()
        destination = os.path.join(run_dir, f"download{extension}")

        opener = urllib.request.build_opener(_ValidatingRedirectHandler)
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
                raise MediaValidationError(
                    f"That file is over the {self._settings.max_file_size_mb}MB limit."
                )

            total = 0
            with open(destination, "wb") as out_file:
                while chunk := response.read(_CHUNK_SIZE):
                    total += len(chunk)
                    if total > max_bytes:
                        raise MediaValidationError(
                            f"That file is over the {self._settings.max_file_size_mb}MB limit."
                        )
                    out_file.write(chunk)

        if total == 0:
            raise MediaValidationError("That link returned an empty file.")
        return destination
