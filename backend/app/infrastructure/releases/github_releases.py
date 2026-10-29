"""Reads the app's own release history from the GitHub Releases API.

This exists because the repository is private. An unauthenticated call from a
browser 404s, and a token cannot be shipped in client-side JavaScript - the
constraint that previously pushed this read into CI, which then had to commit
the answer back into the repo as a static file.

Doing the read here instead removes that commit entirely. The token stays
server-side, the client asks its own backend, and no bot ever writes to git.
"""

import asyncio
import json
import re
import urllib.error
import urllib.request

from ...domain.entities import LatestRelease, ReleaseEntry, ReleaseIndex
from ..config import Settings

_TIMEOUT_SECONDS = 10
_PER_PAGE = 30

# Release tags are written by production-environment.yml as
# `v<version>-build<code>`; the build number is the Android versionCode an
# installed APK compares itself against.
#
# The `dev-` prefix is optional because releases used to be published from the
# dev branch under `dev-v<version>-build<code>`, and builds 1-30 still carry
# that form. Dropping it here would make every one of them unparseable, which
# does not just shorten a list: `latest` is the first *parseable* tag, so a
# device sitting on one of those builds would be told nothing newer exists.
_TAG = re.compile(r"^(?:dev-)?v(?P<version>\d+\.\d+\.\d+)-build(?P<code>\d+)$")


class GithubReleaseCatalog:
    """ReleaseCatalog adapter backed by the GitHub Releases API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return bool(self._settings.github_token.strip() and self._settings.github_repo.strip())

    async def fetch(self) -> ReleaseIndex:
        if not self.configured:
            # An unconfigured catalog is empty, not broken: the Releases tab
            # renders nothing and the update check no-ops, which is the same
            # outcome the static file produced when CI had never run.
            return ReleaseIndex(releases=[])
        payload = await asyncio.to_thread(self._get)
        return self._to_index(payload)

    def _get(self) -> list[dict]:
        url = (
            f"https://api.github.com/repos/{self._settings.github_repo.strip()}"
            f"/releases?per_page={_PER_PAGE}"
        )
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "VideoLens",
                "Authorization": f"Bearer {self._settings.github_token.strip()}",
            },
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _to_index(payload: list[dict]) -> ReleaseIndex:
        entries: list[ReleaseEntry] = []
        latest: LatestRelease | None = None

        for release in payload:
            if release.get("draft"):
                continue
            tag = release.get("tag_name") or ""
            entry = ReleaseEntry(
                name=release.get("name") or tag,
                tag=tag,
                published_at=release.get("published_at") or "",
                url=release.get("html_url") or "",
            )
            entries.append(entry)

            # GitHub returns newest first, so the first parseable tag is the
            # newest build. Anything that does not match the scheme is still
            # listed, it just cannot answer "is there an update".
            match = _TAG.match(tag)
            if latest is None and match:
                latest = LatestRelease(
                    version_code=int(match.group("code")),
                    version_name=match.group("version"),
                    url=entry.url,
                )

        return ReleaseIndex(releases=entries, latest=latest)
