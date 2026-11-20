import unittest
from unittest import mock

from app.domain.entities import SpendClaim
from app.infrastructure.config import Settings
from app.infrastructure.quota import daily_budget
from app.infrastructure.quota.daily_budget import DailyBudget


class DailyBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = Settings(daily_run_cap=2)
        self.budget = DailyBudget(self.settings)

    async def test_allows_runs_up_to_the_cap(self) -> None:
        self.assertTrue(await self.budget.try_consume())
        self.assertTrue(await self.budget.try_consume())

    async def test_rejects_once_cap_is_exceeded(self) -> None:
        await self.budget.try_consume()
        await self.budget.try_consume()
        self.assertFalse(await self.budget.try_consume())

    async def test_zero_cap_disables_the_limit(self) -> None:
        self.settings.daily_run_cap = 0
        for _ in range(5):
            self.assertTrue(await self.budget.try_consume())

    async def test_a_refused_consume_takes_nothing(self) -> None:
        await self.budget.try_consume()
        await self.budget.try_consume()
        self.assertIsNone(await self.budget.try_consume())
        # One run handed back frees exactly one: refused attempts never
        # pushed the counter past the cap.
        await self.budget.refund(SpendClaim(day=daily_budget._today()))
        self.assertIsNotNone(await self.budget.try_consume())
        self.assertIsNone(await self.budget.try_consume())

    async def test_refund_never_goes_below_zero(self) -> None:
        claim = await self.budget.try_consume()
        await self.budget.refund(claim)
        await self.budget.refund(claim)
        self.assertEqual(await self.budget.remaining(), 2)

    async def test_refund_lands_on_the_day_it_was_taken(self) -> None:
        with mock.patch.object(daily_budget, "_today", return_value="2026-11-19"):
            claim = await self.budget.try_consume()
        with mock.patch.object(daily_budget, "_today", return_value="2026-11-20"):
            await self.budget.try_consume()
            await self.budget.try_consume()
            await self.budget.refund(claim)
            # Yesterday's unit is not today's: today is still full.
            self.assertEqual(await self.budget.remaining(), 0)

    async def test_hold_and_release_hand_back_once(self) -> None:
        claim = await self.budget.try_consume()
        await self.budget.hold("run-1", claim)
        self.assertTrue(await self.budget.release("run-1", refund=True))
        self.assertFalse(await self.budget.release("run-1", refund=True))
        self.assertEqual(await self.budget.remaining(), 2)

    async def test_release_without_refund_keeps_the_unit(self) -> None:
        claim = await self.budget.try_consume()
        await self.budget.hold("run-1", claim)
        self.assertFalse(await self.budget.release("run-1", refund=False))
        self.assertEqual(await self.budget.remaining(), 1)

    async def test_uncapped_claim_holds_and_refunds_nothing(self) -> None:
        self.settings.daily_run_cap = 0
        claim = await self.budget.try_consume()
        self.assertFalse(claim.counted)
        await self.budget.hold("run-1", claim)
        self.assertFalse(await self.budget.release("run-1", refund=True))


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
        out = []
        for op, key in self._ops:
            out.append(self._store.get(key) if op == "get" else int(self._store.pop(key, None) is not None))
        return out


class _FakeRedis:
    """Runs the adapter's two scripts by meaning (not by Lua), and records
    the keys they were sent, which is what decides the day a refund hits."""

    def __init__(self) -> None:
        self.store: dict = {}
        self.evals: list = []

    async def eval(self, script, numkeys, *args):
        keys, argv = list(args[:numkeys]), list(args[numkeys:])
        self.evals.append((script, keys))
        used = int(self.store.get(keys[0], 0))
        if script is daily_budget._CONSUME:
            if used >= int(argv[0]):
                return 0
            self.store[keys[0]] = used + 1
            return 1
        if used > 0:
            self.store[keys[0]] = used - 1
        return 1

    async def set(self, key, value, ex=None) -> None:
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self.store)


class DistributedDailyBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = Settings(daily_run_cap=1, redis_url="redis://localhost:6379/0")
        self.budget = DailyBudget(self.settings)
        self.redis = _FakeRedis()
        self.budget._redis = self.redis

    async def test_settings_are_distributed(self) -> None:
        self.assertTrue(self.settings.queue_enabled)

    async def test_release_refunds_the_held_day_once(self) -> None:
        with mock.patch.object(daily_budget, "_today", return_value="2026-11-19"):
            claim = await self.budget.try_consume()
            await self.budget.hold("run-1", claim)
            self.assertIsNone(await self.budget.try_consume())
        with mock.patch.object(daily_budget, "_today", return_value="2026-11-20"):
            self.assertTrue(await self.budget.release("run-1", refund=True))
            self.assertFalse(await self.budget.release("run-1", refund=True))
        refunds = [keys for script, keys in self.redis.evals if script is daily_budget._REFUND]
        self.assertEqual(refunds, [["videolens:runs:2026-11-19"]])
        self.assertEqual(self.redis.store["videolens:runs:2026-11-19"], 0)

    async def test_scripts_guard_the_counter(self) -> None:
        # The refund never decrements a counter at or below zero, and the
        # consume never increments one already at the cap.
        self.assertIn("> 0", daily_budget._REFUND)
        self.assertIn(">= tonumber(ARGV[1]) then return 0", daily_budget._CONSUME)


if __name__ == "__main__":
    unittest.main()
