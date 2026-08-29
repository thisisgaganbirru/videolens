"""Concrete capability probes.

Each one owns the question "is my dependency actually usable?" for exactly one
dependency, and answers it by *exercising* that dependency wherever exercising
it is cheap and free of side effects. Where it is not - a Gemini key cannot be
validated without spending a request against it - the probe says so with
`probed=False` instead of quietly reporting the presence of configuration as
if it were proof the thing works.
"""

import asyncio
import os
from datetime import date, datetime

from ...domain.entities import Capability, CapabilityState
from ..config import Settings
from ..media.ffmpeg import _media_binary

_VERSION_TIMEOUT_SECONDS = 5.0

# yt-dlp ships date-stamped releases and platforms break it constantly; an old
# copy is the single most common reason URL runs start failing.
_YTDLP_STALE_AFTER_DAYS = 120


class MediaToolsProbe:
    """Runs `ffmpeg -version` / `ffprobe -version`. Resolving the path only
    proves a file exists; executing it proves the container can run it."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "media_tools"

    async def check(self) -> Capability:
        versions = []
        for binary in ("ffmpeg", "ffprobe"):
            try:
                path = await asyncio.to_thread(_media_binary, self._settings, binary)
            except Exception as exc:  # noqa: BLE001 - message is already caller-safe
                return Capability(
                    name=self.name,
                    state=CapabilityState.UNAVAILABLE,
                    detail="Media processing is unavailable.",
                    probed=True,
                    log_detail=str(exc),
                )
            version = await self._version_of(path)
            if version is None:
                return Capability(
                    name=self.name,
                    state=CapabilityState.UNAVAILABLE,
                    detail="Media processing is unavailable.",
                    probed=True,
                    log_detail=f"{binary} was found at {path} but did not run.",
                )
            versions.append(f"{binary} {version}")
        return Capability(
            name=self.name,
            state=CapabilityState.OK,
            detail="Media processing is available.",
            probed=True,
            log_detail=", ".join(versions),
        )

    @staticmethod
    async def _version_of(path: str) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                path,
                "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), _VERSION_TIMEOUT_SECONDS)
        except (OSError, asyncio.TimeoutError):
            return None
        if proc.returncode != 0 or not stdout:
            return None
        first_line = stdout.decode(errors="ignore").splitlines()[0]
        parts = first_line.split()
        return parts[2] if len(parts) > 2 else first_line


class RunStoreProbe:
    """Pings Redis in distributed mode. In local mode the store is a dict in
    this process, so there is nothing to ping - reported as working but
    explicitly not probed, and named as non-durable."""

    def __init__(self, run_repository, *, distributed: bool) -> None:
        self._runs = run_repository
        self._distributed = distributed

    @property
    def name(self) -> str:
        return "run_store"

    async def check(self) -> Capability:
        if not self._distributed:
            return Capability(
                name=self.name,
                state=CapabilityState.OK,
                detail="Runs are not saved and will be lost if the server restarts.",
                probed=False,
                log_detail="in-process store; not durable, not shared across replicas",
            )
        reachable = await self._runs.ping()
        if not reachable:
            return Capability(
                name=self.name,
                state=CapabilityState.UNAVAILABLE,
                detail="Runs cannot be saved right now.",
                probed=True,
                log_detail="redis did not respond to a ping",
            )
        return Capability(
            name=self.name,
            state=CapabilityState.OK,
            detail="Runs are being saved.",
            probed=True,
            log_detail="redis reachable",
        )


class ObjectStoreProbe:
    """Object storage is optional. Unconfigured is reported as DISABLED, which
    is a statement of topology rather than a fault; configured means the
    bucket is actually contacted."""

    def __init__(self, object_store) -> None:
        self._storage = object_store

    @property
    def name(self) -> str:
        return "object_storage"

    async def check(self) -> Capability:
        if not self._storage.enabled:
            return Capability(
                name=self.name,
                state=CapabilityState.DISABLED,
                detail="Uploads are handled without external storage.",
                probed=False,
                log_detail="object storage not configured; uploads stay on local disk",
            )
        try:
            await self._storage.check_bucket()
        except Exception:  # noqa: BLE001 - boto errors carry endpoint/credential detail
            return Capability(
                name=self.name,
                state=CapabilityState.UNAVAILABLE,
                detail="Upload storage is unreachable.",
                probed=True,
                log_detail="head_bucket failed; see the logged exception",
            )
        return Capability(
            name=self.name,
            state=CapabilityState.OK,
            detail="Upload storage is available.",
            probed=True,
            log_detail="bucket reachable",
        )


class UrlDownloadProbe:
    """Reports the yt-dlp build and the cookie source, without fetching
    anything. A configured-but-missing cookie file is the exact failure this
    catches: URL runs keep working for public sources and fail only on the
    login-walled ones, which is invisible until someone submits one."""

    def __init__(self, settings: Settings, *, today: date | None = None) -> None:
        self._settings = settings
        self._today = today

    @property
    def name(self) -> str:
        return "url_download"

    async def check(self) -> Capability:
        try:
            from yt_dlp.version import __version__ as ytdlp_version
        except Exception:  # noqa: BLE001
            return Capability(
                name=self.name,
                state=CapabilityState.UNAVAILABLE,
                detail="yt-dlp is not importable; URL runs cannot start.",
                probed=True,
            )

        notes: list[str] = []
        operator_notes = [f"yt-dlp {ytdlp_version}"]
        state = CapabilityState.OK

        age_days = self._release_age_days(ytdlp_version)
        if age_days is not None and age_days > _YTDLP_STALE_AFTER_DAYS:
            state = CapabilityState.DEGRADED
            operator_notes.append(
                f"released {age_days} days ago; extractors for major sites are likely stale"
            )
            notes.append("Link downloads may fail on major sites.")

        cookie_file = self._settings.ytdlp_cookies_file.strip()
        browser = self._settings.ytdlp_cookies_from_browser.strip()
        if cookie_file and browser:
            operator_notes.append("two conflicting cookie sources are configured")
            return Capability(
                name=self.name,
                state=CapabilityState.DEGRADED,
                detail="Links behind a login will fail.",
                probed=True,
                log_detail="; ".join(operator_notes),
            )
        if cookie_file:
            resolved = os.path.abspath(os.path.expanduser(cookie_file))
            if os.path.isfile(resolved):
                operator_notes.append("cookie file present")
            else:
                state = CapabilityState.DEGRADED
                operator_notes.append("configured cookie file is missing")
                notes.append("Links behind a login will fail.")
        elif browser:
            operator_notes.append(f"cookies from browser: {browser}")
        else:
            operator_notes.append("no cookies configured")
            notes.append("Links behind a login will fail.")

        return Capability(
            name=self.name,
            state=state,
            detail=" ".join(notes) or "Link downloads are available.",
            probed=True,
            log_detail="; ".join(operator_notes),
        )

    def _release_age_days(self, version: str) -> int | None:
        """yt-dlp versions are YYYY.MM.DD. Anything else is not aged."""
        try:
            released = datetime.strptime(version.split(".dev")[0][:10], "%Y.%m.%d").date()
        except ValueError:
            return None
        return ((self._today or date.today()) - released).days


class AnalysisEngineProbe:
    """Cannot be probed: the only way to prove a Gemini key works is to spend
    a request with it. So this reports configuration and says outright that it
    was not verified, rather than showing a green light that means nothing."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "analysis_engine"

    async def check(self) -> Capability:
        model = self._settings.gemini_model
        if self._settings.gemini_api_key.strip():
            return Capability(
                name=self.name,
                state=CapabilityState.OK,
                detail="Analysis is configured. Not verified - checking would spend quota.",
                probed=False,
                log_detail=f"shared key configured for {model}; not probed",
            )
        return Capability(
            name=self.name,
            state=CapabilityState.DEGRADED,
            detail=(
                "No shared analysis key is configured. Callers who bring their own key "
                "still work; everyone else fails at analysis."
            ),
            probed=False,
            log_detail=f"no shared key configured for {model}",
        )


class DailyBudgetProbe:
    """Reads today's remaining run allowance without consuming any of it."""

    def __init__(self, spend_cap) -> None:
        self._spend_cap = spend_cap

    @property
    def name(self) -> str:
        return "daily_budget"

    async def check(self) -> Capability:
        remaining = await self._spend_cap.remaining()
        if remaining is None:
            return Capability(
                name=self.name,
                state=CapabilityState.DISABLED,
                detail="No daily cap configured.",
                probed=True,
            )
        if remaining == 0:
            return Capability(
                name=self.name,
                state=CapabilityState.UNAVAILABLE,
                detail=(
                    "Today's shared run budget is exhausted. Bring-your-own-key runs "
                    "are unaffected."
                ),
                probed=True,
            )
        return Capability(
            name=self.name,
            state=CapabilityState.OK,
            detail="Shared runs are available today.",
            probed=True,
            log_detail=f"{remaining} shared runs remaining today",
        )
