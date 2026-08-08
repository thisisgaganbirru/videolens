import unittest

from app.budget import DailyBudget
from app.config import settings


class DailyBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._original_cap = settings.daily_run_cap
        settings.daily_run_cap = 2
        self.budget = DailyBudget()

    async def asyncTearDown(self) -> None:
        settings.daily_run_cap = self._original_cap

    async def test_allows_runs_up_to_the_cap(self) -> None:
        self.assertTrue(await self.budget.try_consume())
        self.assertTrue(await self.budget.try_consume())

    async def test_rejects_once_cap_is_exceeded(self) -> None:
        await self.budget.try_consume()
        await self.budget.try_consume()
        self.assertFalse(await self.budget.try_consume())

    async def test_zero_cap_disables_the_limit(self) -> None:
        settings.daily_run_cap = 0
        for _ in range(5):
            self.assertTrue(await self.budget.try_consume())


if __name__ == "__main__":
    unittest.main()
