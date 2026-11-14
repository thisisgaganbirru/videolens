import unittest
from unittest.mock import patch

from app.infrastructure.config import Settings
from app.infrastructure.quota import long_run_guard
from app.infrastructure.quota.long_run_guard import LongRunSlots


class InMemoryLongRunSlotsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.slots = LongRunSlots(Settings(redis_url="", worker_long_job_timeout_seconds=1800))

    async def test_one_run_per_key(self) -> None:
        self.assertTrue(await self.slots.try_acquire("acct-1", "r1"))
        self.assertFalse(await self.slots.try_acquire("acct-1", "r2"))
        # Other accounts are independent.
        self.assertTrue(await self.slots.try_acquire("acct-2", "r3"))

    async def test_the_holder_may_claim_again(self) -> None:
        self.assertTrue(await self.slots.try_acquire("acct-1", "r1"))
        self.assertTrue(await self.slots.try_acquire("acct-1", "r1"))

    async def test_only_the_holder_releases(self) -> None:
        await self.slots.try_acquire("acct-1", "r1")
        await self.slots.release("acct-1", "r2")
        self.assertFalse(await self.slots.try_acquire("acct-1", "r2"))
        await self.slots.release("acct-1", "r1")
        self.assertTrue(await self.slots.try_acquire("acct-1", "r2"))

    async def test_expires_after_the_long_job_timeout_plus_margin(self) -> None:
        self.assertEqual(self.slots.ttl_seconds, 1920)
        clock = [1000.0]
        with patch.object(long_run_guard.time, "monotonic", lambda: clock[0]):
            await self.slots.try_acquire("acct-1", "r1")
            clock[0] += 1919
            self.assertFalse(await self.slots.try_acquire("acct-1", "r2"))
            clock[0] += 2
            # A worker that died mid-run does not lock the account out.
            self.assertTrue(await self.slots.try_acquire("acct-1", "r2"))

    async def test_ttl_never_below_the_standard_timeout(self) -> None:
        slots = LongRunSlots(Settings(worker_job_timeout_seconds=900, worker_long_job_timeout_seconds=60))
        self.assertEqual(slots.ttl_seconds, 1020)


if __name__ == "__main__":
    unittest.main()
