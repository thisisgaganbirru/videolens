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


if __name__ == "__main__":
    unittest.main()
