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


    async def test_a_held_run_is_handed_back_on_release(self) -> None:
        store = self._store(per_device=1, per_ip=1)
        claim = await store.try_consume("dev-a", "1.1.1.1")
        await store.hold("run-1", claim)
        self.assertTrue(await store.release("run-1", refund=True))
        self.assertEqual((await store.status("dev-a")).used, 0)
        self.assertIsNotNone(await store.try_consume("dev-b", "1.1.1.1"))

    async def test_release_refunds_at_most_once(self) -> None:
        store = self._store(per_device=3)
        await store.try_consume("dev-a", "1.1.1.1")
        claim = await store.try_consume("dev-a", "1.1.1.1")
        await store.hold("run-1", claim)
        self.assertTrue(await store.release("run-1", refund=True))
        self.assertFalse(await store.release("run-1", refund=True))
        self.assertEqual((await store.status("dev-a")).used, 1)

    async def test_release_without_refund_just_forgets(self) -> None:
        store = self._store()
        claim = await store.try_consume("dev-a", "1.1.1.1")
        await store.hold("run-1", claim)
        self.assertFalse(await store.release("run-1", refund=False))
        self.assertFalse(await store.release("run-1", refund=True))
        self.assertEqual((await store.status("dev-a")).used, 1)

    async def test_releasing_a_run_that_held_nothing_is_a_no_op(self) -> None:
        store = self._store()
        await store.try_consume("dev-a", "1.1.1.1")
        self.assertFalse(await store.release("byok-run", refund=True))
        self.assertEqual((await store.status("dev-a")).used, 1)

    async def test_a_held_refund_after_midnight_goes_to_the_claims_day(self) -> None:
        store = self._store(per_device=1)
        with patch.object(free_run_allowance, "_today", return_value="2026-11-01"):
            claim = await store.try_consume("dev-a", "1.1.1.1")
            await store.hold("run-1", claim)
        with patch.object(free_run_allowance, "_today", return_value="2026-11-02"):
            self.assertIsNotNone(await store.try_consume("dev-a", "1.1.1.1"))
            await store.release("run-1", refund=True)
            # Today's run stays spent: the refund belonged to yesterday.
            self.assertEqual((await store.status("dev-a")).used, 1)

    async def test_a_hold_never_stores_the_raw_ip(self) -> None:
        store = self._store()
        claim = await store.try_consume("dev-a", "203.0.113.7")
        await store.hold("run-1", claim)
        self.assertNotIn("203.0.113.7", repr(store._held))


class _FakePipeline:
    def __init__(self, store: dict) -> None:
        self._store = store
        self._ops: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    def get(self, key: str) -> None:
        self._ops.append(("get", key))

    def delete(self, key: str) -> None:
        self._ops.append(("delete", key))

    async def execute(self) -> list:
        return [self._store.get(key) if op == "get" else int(self._store.pop(key, None) is not None) for op, key in self._ops]


class _FakeRedis:
    """Runs the adapter's two scripts by meaning (not by Lua) and keeps every
    value it was sent, so the test can look at what Redis would hold."""

    def __init__(self) -> None:
        self.store: dict = {}
        self.evals: list = []

    async def eval(self, script, numkeys, *args):
        keys, argv = list(args[:numkeys]), list(args[numkeys:])
        self.evals.append((script, keys))
        if script is free_run_allowance._CONSUME:
            if any(int(self.store.get(key, 0)) >= int(limit) for key, limit in zip(keys, argv)):
                return 0
            for key in keys:
                self.store[key] = int(self.store.get(key, 0)) + 1
            return 1
        for key in keys:
            if int(self.store.get(key, 0)) > 0:
                self.store[key] = int(self.store[key]) - 1
        return 1

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None) -> None:
        self.store[key] = value

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self.store)

    async def aclose(self) -> None:
        self.closed = True


class DistributedFreeRunAllowanceTests(unittest.IsolatedAsyncioTestCase):
    """The Redis path (`REDIS_URL` set), over a fake client: the same rules as
    local mode, the hold stored as hashed keys only, released at most once."""

    async def asyncSetUp(self) -> None:
        self.store = FreeRunAllowanceStore(
            Settings(_env_file=None, redis_url="redis://localhost:6379/0", free_runs_per_device=1, free_runs_per_ip=5)
        )
        self.redis = _FakeRedis()
        self.store._redis = self.redis

    async def test_consume_is_refused_at_the_device_limit_and_status_reads_redis(self) -> None:
        self.assertIsNotNone(await self.store.try_consume("dev-a", "203.0.113.7"))
        self.assertIsNone(await self.store.try_consume("dev-a", "203.0.113.7"))
        status = await self.store.status("dev-a")
        self.assertEqual((status.used, status.remaining), (1, 0))
        # Both counters in one script call, the IP hashed into its key name.
        keys = self.redis.evals[0][1]
        self.assertEqual(len(keys), 2)
        self.assertNotIn("203.0.113.7", " ".join(keys))

    async def test_a_hold_is_released_once_and_never_stores_the_raw_ip(self) -> None:
        with patch.object(free_run_allowance, "_today", return_value="2026-11-19"):
            claim = await self.store.try_consume("dev-a", "203.0.113.7")
            await self.store.hold("run-1", claim)
        held = self.redis.store["videolens:free:held:run-1"]
        self.assertNotIn("203.0.113.7", held)
        with patch.object(free_run_allowance, "_today", return_value="2026-11-20"):
            self.assertTrue(await self.store.release("run-1", refund=True))
            self.assertFalse(await self.store.release("run-1", refund=True))
        refunds = [keys for script, keys in self.redis.evals if script is free_run_allowance._REFUND]
        # Handed back to the claim's own day, not to the day of the release.
        self.assertEqual(len(refunds), 1)
        self.assertTrue(all(":2026-11-19:" in key for key in refunds[0]))
        self.assertNotIn("videolens:free:held:run-1", self.redis.store)

    async def test_release_without_refund_just_forgets_the_hold(self) -> None:
        claim = await self.store.try_consume("dev-a", "203.0.113.7")
        await self.store.hold("run-1", claim)
        self.assertFalse(await self.store.release("run-1", refund=False))
        self.assertEqual((await self.store.status("dev-a")).used, 1)
        self.assertNotIn("videolens:free:held:run-1", self.redis.store)

    async def test_close_closes_the_client_once(self) -> None:
        await self.store.close()
        self.assertTrue(self.redis.closed)
        self.assertIsNone(self.store._redis)
        await self.store.close()  # a second close is harmless

    async def test_scripts_check_every_counter_before_taking_any(self) -> None:
        consume = free_run_allowance._CONSUME
        self.assertLess(consume.index("return 0"), consume.index("INCR"))
        self.assertIn("> 0", free_run_allowance._REFUND)


if __name__ == "__main__":
    unittest.main()
