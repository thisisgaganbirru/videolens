import unittest

from app.application.list_runs import ListRunsUseCase
from app.domain.entities import Principal

from .fakes import FakeRunRepository


class ListRunsUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.use_case = ListRunsUseCase(runs=self.runs)

    async def test_returns_only_the_calling_principals_runs(self) -> None:
        await self.runs.create("run-a", "client:owner-1")
        await self.runs.create("run-b", "client:owner-2")
        await self.runs.create("run-c", "client:owner-1")
        principal = Principal(subject="client:owner-1", authenticated=False)

        runs = await self.use_case.execute(principal)

        self.assertEqual(sorted(run.run_id for run in runs), ["run-a", "run-c"])

    async def test_returns_an_empty_list_for_an_owner_with_no_runs(self) -> None:
        principal = Principal(subject="client:nobody", authenticated=False)

        runs = await self.use_case.execute(principal)

        self.assertEqual(runs, [])


if __name__ == "__main__":
    unittest.main()
