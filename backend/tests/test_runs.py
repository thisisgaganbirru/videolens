import unittest

from app.models import RunStatus, VideoAnalysis
from app.runs import RunStore


class RunStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = RunStore()

    async def test_run_lifecycle_keeps_owner(self) -> None:
        run = await self.store.create("run-1", "client:test-client-1234")
        self.assertEqual(run.status, RunStatus.QUEUED)
        self.assertEqual(run.owner_id, "client:test-client-1234")

        await self.store.set_stage(run.run_id, "analyzing")
        await self.store.set_result(
            run.run_id,
            VideoAnalysis(
                title="Test",
                summary="Summary",
                transcript="Transcript",
                screen_text="",
                markdown="# Test",
            ),
        )

        saved = await self.store.get(run.run_id)
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.owner_id, run.owner_id)
        self.assertEqual(saved.status, RunStatus.COMPLETE)
        self.assertEqual(saved.stage, "analyzing")

    async def test_list_for_owner_returns_only_that_owners_runs_newest_first(self) -> None:
        await self.store.create("run-a", "client:owner-1")
        await self.store.create("run-b", "client:owner-2")
        await self.store.create("run-c", "client:owner-1")

        history = await self.store.list_for_owner("client:owner-1")

        self.assertEqual([run.run_id for run in history], ["run-c", "run-a"])

    async def test_list_for_owner_respects_limit(self) -> None:
        for i in range(5):
            await self.store.create(f"run-{i}", "client:owner-1")

        history = await self.store.list_for_owner("client:owner-1", limit=2)

        self.assertEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
