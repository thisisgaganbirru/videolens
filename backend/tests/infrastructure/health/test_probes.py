import os
import tempfile
import unittest
from datetime import date

from app.domain.entities import CapabilityState
from app.infrastructure.config import Settings
from app.infrastructure.health.probes import (
    AnalysisEngineProbe,
    DailyBudgetProbe,
    ObjectStoreProbe,
    RunStoreProbe,
    UrlDownloadProbe,
)


class FakeRunRepository:
    def __init__(self, reachable: bool = True) -> None:
        self.reachable = reachable
        self.pings = 0

    async def ping(self) -> bool:
        self.pings += 1
        return self.reachable


class FakeObjectStore:
    def __init__(self, *, enabled: bool, error: Exception | None = None) -> None:
        self.enabled = enabled
        self.error = error
        self.checks = 0

    async def check_bucket(self) -> None:
        self.checks += 1
        if self.error:
            raise self.error


class FakeSpendCap:
    def __init__(self, remaining_runs: int | None) -> None:
        self._remaining = remaining_runs

    async def remaining(self) -> int | None:
        return self._remaining


class RunStoreProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_mode_is_ok_but_explicitly_not_probed(self) -> None:
        runs = FakeRunRepository()
        capability = await RunStoreProbe(runs, distributed=False).check()

        self.assertEqual(capability.state, CapabilityState.OK)
        self.assertFalse(capability.probed)
        self.assertIn("lost on restart", capability.detail)
        # ping() returns True unconditionally in local mode, so calling it
        # would have produced a green light that proves nothing.
        self.assertEqual(runs.pings, 0)

    async def test_distributed_mode_actually_pings(self) -> None:
        runs = FakeRunRepository()
        capability = await RunStoreProbe(runs, distributed=True).check()

        self.assertEqual(capability.state, CapabilityState.OK)
        self.assertTrue(capability.probed)
        self.assertEqual(runs.pings, 1)

    async def test_unreachable_redis_is_unavailable(self) -> None:
        capability = await RunStoreProbe(FakeRunRepository(reachable=False), distributed=True).check()

        self.assertEqual(capability.state, CapabilityState.UNAVAILABLE)


class ObjectStoreProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured_storage_is_disabled_not_broken(self) -> None:
        storage = FakeObjectStore(enabled=False)
        capability = await ObjectStoreProbe(storage).check()

        self.assertEqual(capability.state, CapabilityState.DISABLED)
        self.assertFalse(capability.probed)
        self.assertEqual(storage.checks, 0)

    async def test_configured_storage_is_contacted(self) -> None:
        storage = FakeObjectStore(enabled=True)
        capability = await ObjectStoreProbe(storage).check()

        self.assertEqual(capability.state, CapabilityState.OK)
        self.assertTrue(capability.probed)
        self.assertEqual(storage.checks, 1)

    async def test_unreachable_bucket_is_unavailable_without_leaking_the_error(self) -> None:
        storage = FakeObjectStore(
            enabled=True, error=RuntimeError("InvalidAccessKeyId AKIAsecret endpoint=internal")
        )
        capability = await ObjectStoreProbe(storage).check()

        self.assertEqual(capability.state, CapabilityState.UNAVAILABLE)
        self.assertNotIn("AKIAsecret", capability.detail)


class UrlDownloadProbeTests(unittest.IsolatedAsyncioTestCase):
    def _settings(self, **overrides) -> Settings:
        return Settings(gemini_api_key="k", **overrides)

    async def test_reports_the_ytdlp_version(self) -> None:
        capability = await UrlDownloadProbe(self._settings()).check()

        self.assertIn("yt-dlp", capability.detail)
        self.assertTrue(capability.probed)

    async def test_no_cookies_configured_is_still_ok_but_says_so(self) -> None:
        capability = await UrlDownloadProbe(self._settings(), today=date(2000, 1, 1)).check()

        self.assertEqual(capability.state, CapabilityState.OK)
        self.assertIn("no cookies configured", capability.detail)

    async def test_a_missing_cookie_file_degrades_the_capability(self) -> None:
        settings = self._settings(ytdlp_cookies_file="/nope/cookies.txt")
        capability = await UrlDownloadProbe(settings, today=date(2000, 1, 1)).check()

        self.assertEqual(capability.state, CapabilityState.DEGRADED)
        self.assertIn("missing", capability.detail)

    async def test_a_present_cookie_file_is_ok(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
            handle.write(b"# Netscape HTTP Cookie File\n")
            path = handle.name
        try:
            settings = self._settings(ytdlp_cookies_file=path)
            capability = await UrlDownloadProbe(settings, today=date(2000, 1, 1)).check()

            self.assertEqual(capability.state, CapabilityState.OK)
            self.assertIn("cookie file present", capability.detail)
        finally:
            os.unlink(path)

    async def test_configuring_both_cookie_sources_degrades_the_capability(self) -> None:
        settings = self._settings(
            ytdlp_cookies_file="/nope/cookies.txt", ytdlp_cookies_from_browser="chrome"
        )
        capability = await UrlDownloadProbe(settings, today=date(2000, 1, 1)).check()

        self.assertEqual(capability.state, CapabilityState.DEGRADED)
        self.assertIn("both", capability.detail)

    async def test_a_stale_ytdlp_build_degrades_the_capability(self) -> None:
        # Far-future "today" makes whatever version is installed look ancient.
        capability = await UrlDownloadProbe(self._settings(), today=date(2099, 1, 1)).check()

        self.assertEqual(capability.state, CapabilityState.DEGRADED)
        self.assertIn("stale", capability.detail)


class AnalysisEngineProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_configured_key_is_ok_but_marked_unprobed(self) -> None:
        capability = await AnalysisEngineProbe(Settings(gemini_api_key="k")).check()

        self.assertEqual(capability.state, CapabilityState.OK)
        # Verifying the key means spending a request, so this must never
        # claim to have checked it.
        self.assertFalse(capability.probed)
        self.assertIn("Not verified", capability.detail)

    async def test_a_missing_key_is_degraded_because_byok_still_works(self) -> None:
        capability = await AnalysisEngineProbe(Settings(gemini_api_key="")).check()

        self.assertEqual(capability.state, CapabilityState.DEGRADED)
        self.assertIn("X-Gemini-Api-Key", capability.detail)

    async def test_never_includes_the_key_itself(self) -> None:
        capability = await AnalysisEngineProbe(Settings(gemini_api_key="AIzaSecretValue")).check()

        self.assertNotIn("AIzaSecretValue", capability.detail)


class DailyBudgetProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_remaining_runs(self) -> None:
        capability = await DailyBudgetProbe(FakeSpendCap(17)).check()

        self.assertEqual(capability.state, CapabilityState.OK)
        self.assertIn("17", capability.detail)

    async def test_an_exhausted_budget_is_unavailable(self) -> None:
        capability = await DailyBudgetProbe(FakeSpendCap(0)).check()

        self.assertEqual(capability.state, CapabilityState.UNAVAILABLE)
        self.assertIn("Bring-your-own-key", capability.detail)

    async def test_no_cap_configured_is_disabled(self) -> None:
        capability = await DailyBudgetProbe(FakeSpendCap(None)).check()

        self.assertEqual(capability.state, CapabilityState.DISABLED)


if __name__ == "__main__":
    unittest.main()
