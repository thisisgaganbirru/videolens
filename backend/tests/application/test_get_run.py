import unittest

from app.application.get_run import GetRunUseCase
from app.domain.entities import Principal
from app.domain.errors import RunNotFoundError

from .fakes import FakeRunRepository


class GetRunUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.use_case = GetRunUseCase(runs=self.runs)

    async def test_returns_the_run_when_the_owner_matches(self) -> None:
        created = await self.runs.create("run-1", "client:owner-1")
        principal = Principal(subject="client:owner-1", authenticated=False)

        run = await self.use_case.execute("run-1", principal)

        self.assertEqual(run.run_id, created.run_id)

    async def test_raises_not_found_when_the_run_does_not_exist(self) -> None:
        principal = Principal(subject="client:owner-1", authenticated=False)
        with self.assertRaises(RunNotFoundError):
            await self.use_case.execute("does-not-exist", principal)

    async def test_raises_not_found_rather_than_leaking_another_owners_run(self) -> None:
        await self.runs.create("run-1", "client:owner-1")
        other_principal = Principal(subject="client:owner-2", authenticated=False)

        with self.assertRaises(RunNotFoundError):
            await self.use_case.execute("run-1", other_principal)


if __name__ == "__main__":
    unittest.main()
