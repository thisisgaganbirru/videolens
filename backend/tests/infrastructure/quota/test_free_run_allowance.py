import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.domain.entities import FreeRunClaim
from app.infrastructure.config import Settings
from app.infrastructure.quota import free_run_allowance
from app.infrastructure.quota.free_run_allowance import FreeRunAllowanceStore


class FreeRunAllowanceStoreTests(unittest.IsolatedAsyncioTestCase):
    """Local (in-process) mode. The Redis path runs the same rules as one Lua
    script; there is no Redis in the test environment."""

    def _store(self, per_device: int = 2, per_ip: int = 3) -> FreeRunAllowanceStore:
        return FreeRunAllowanceStore(
            Settings(_env_file=None, free_runs_per_device=per_device, free_runs_per_ip=per_ip)
        )

    async def test_counts_per_device(self) -> None:
        store = self._store()
        self.assertIsNotNone(await store.try_consume("dev-a", "1.1.1.1"))
        self.assertIsNotNone(await store.try_consume("dev-a", "2.2.2.2"))
        self.assertIsNone(await store.try_consume("dev-a", "3.3.3.3"))
        # Another device is unaffected.
        self.assertIsNotNone(await store.try_consume("dev-b", "3.3.3.3"))

    async def test_ip_backstop_bounds_fresh_devices(self) -> None:
        store = self._store(per_device=2, per_ip=3)
        for device in ("dev-a", "dev-b", "dev-c"):
            self.assertIsNotNone(await store.try_consume(device, "1.1.1.1"))
        self.assertIsNone(await store.try_consume("dev-d", "1.1.1.1"))
        self.assertIsNotNone(await store.try_consume("dev-d", "9.9.9.9"))

    async def test_a_rejected_request_takes_nothing(self) -> None:
        store = self._store(per_device=2, per_ip=1)
        await store.try_consume("dev-a", "1.1.1.1")
        # IP full: the device counter must not have moved.
        self.assertIsNone(await store.try_consume("dev-a", "1.1.1.1"))
        self.assertEqual((await store.status("dev-a")).used, 1)

    async def test_zero_ip_limit_disables_only_the_backstop(self) -> None:
        store = self._store(per_device=5, per_ip=0)
        for device in ("a" * 16, "b" * 16, "c" * 16, "d" * 16):
            self.assertIsNotNone(await store.try_consume(device, "1.1.1.1"))

    async def test_status_is_read_only(self) -> None:
        store = self._store(per_device=2)
        await store.try_consume("dev-a", "1.1.1.1")
        for _ in range(3):
            status = await store.status("dev-a")
        self.assertEqual((status.enabled, status.limit, status.used, status.remaining), (True, 2, 1, 1))

    async def test_status_resets_at_next_utc_midnight(self) -> None:
        status = await self._store().status("dev-a")
        self.assertEqual(status.resets_at.tzinfo, timezone.utc)
        self.assertEqual((status.resets_at.hour, status.resets_at.minute), (0, 0))
        self.assertGreater(status.resets_at, datetime.now(timezone.utc))

    async def test_disabled_reports_enabled_false(self) -> None:
        store = self._store(per_device=0)
        self.assertFalse(store.enabled)
        status = await store.status("dev-a")
        self.assertEqual((status.enabled, status.limit, status.used, status.remaining), (False, 0, 0, 0))

    async def test_refund_hands_the_run_back_to_both_counters(self) -> None:
        store = self._store(per_device=1, per_ip=1)
        claim = await store.try_consume("dev-a", "1.1.1.1")
        await store.refund(claim)
        self.assertEqual((await store.status("dev-a")).used, 0)
        self.assertIsNotNone(await store.try_consume("dev-b", "1.1.1.1"))

    async def test_refund_never_goes_below_zero(self) -> None:
        store = self._store()
        await store.refund(FreeRunClaim(device_id="dev-a", client_ip="1.1.1.1", day="2026-11-01"))
        self.assertEqual((await store.status("dev-a")).used, 0)

    async def test_counters_are_per_utc_day(self) -> None:
        store = self._store(per_device=1)
        with patch.object(free_run_allowance, "_today", return_value="2026-11-01"):
            self.assertIsNotNone(await store.try_consume("dev-a", "1.1.1.1"))
            self.assertIsNone(await store.try_consume("dev-a", "1.1.1.1"))
        with patch.object(free_run_allowance, "_today", return_value="2026-11-02"):
            self.assertIsNotNone(await store.try_consume("dev-a", "1.1.1.1"))

    async def test_keys_are_scoped_by_day_and_never_hold_the_raw_ip(self) -> None:
        store = self._store()
        keys = store._keys("2026-11-01", "dev-a", "203.0.113.7")
        self.assertEqual(keys[0], "videolens:free:device:2026-11-01:dev-a")
        self.assertTrue(keys[1].startswith("videolens:free:ip:2026-11-01:"))
        self.assertNotIn("203.0.113.7", keys[1])

    async def test_no_ip_means_no_shared_anonymous_bucket(self) -> None:
        store = self._store(per_device=5, per_ip=1)
        self.assertIsNotNone(await store.try_consume("dev-a", ""))
        self.assertIsNotNone(await store.try_consume("dev-b", ""))


if __name__ == "__main__":
    unittest.main()
