import asyncio
import unittest

from app.infrastructure.config import Settings
from app.infrastructure.queue.job_queue import RunQueue


class FakeKeyVault:
    async def store(self, run_id: str, api_key: str) -> None:
        pass

    async def take(self, run_id: str):
        return None

    async def close(self) -> None:
        pass


class LocalDispatchTests(unittest.IsolatedAsyncioTestCase):
    """Local mode runs jobs as bare asyncio tasks. The event loop keeps only a
    weak reference to a task, so anything the queue does not hold onto can be
    garbage-collected mid-run - the coroutine stops and the run is stranded in
    PROCESSING with nothing left to fail it."""

    def setUp(self) -> None:
        self.settings = Settings(redis_url="")
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.finished: list[str] = []

    async def _runner(self, run_id: str, **kwargs) -> None:
        self.started.set()
        await self.release.wait()
        self.finished.append(run_id)

    async def test_keeps_a_strong_reference_while_the_job_runs(self) -> None:
        queue = RunQueue(self.settings, local_runner=self._runner, key_vault=FakeKeyVault())

        await queue.enqueue("run-1", saved_path="/tmp/x.mp4", run_dir="/tmp")
        await self.started.wait()

        self.assertEqual(len(queue._local_tasks), 1)

        self.release.set()
        await asyncio.gather(*list(queue._local_tasks))
        self.assertEqual(self.finished, ["run-1"])

    async def test_releases_the_reference_once_the_job_completes(self) -> None:
        queue = RunQueue(self.settings, local_runner=self._runner, key_vault=FakeKeyVault())
        self.release.set()

        await queue.enqueue("run-1", saved_path="/tmp/x.mp4", run_dir="/tmp")
        await asyncio.gather(*list(queue._local_tasks))
        await asyncio.sleep(0)

        # Otherwise the set is a slow leak for the life of the process.
        self.assertEqual(len(queue._local_tasks), 0)

    async def test_passes_the_run_arguments_through_to_the_runner(self) -> None:
        seen = {}

        async def runner(run_id: str, **kwargs) -> None:
            seen.update({"run_id": run_id, **kwargs})

        queue = RunQueue(self.settings, local_runner=runner, key_vault=FakeKeyVault())
        await queue.enqueue("run-9", source_url="https://x.test/v", gemini_api_key="byok")
        await asyncio.gather(*list(queue._local_tasks))

        self.assertEqual(seen["run_id"], "run-9")
        self.assertEqual(seen["source_url"], "https://x.test/v")
        self.assertEqual(seen["gemini_api_key"], "byok")


if __name__ == "__main__":
    unittest.main()
