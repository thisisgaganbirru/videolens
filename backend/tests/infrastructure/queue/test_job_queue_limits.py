import unittest
from unittest.mock import AsyncMock, patch

from app.domain.entitlements import MediaLimits, MediaTier
from app.infrastructure.config import Settings
from app.infrastructure.queue import job_queue
from app.infrastructure.queue.job_queue import RunQueue

BIGGER = MediaLimits(
    tier=MediaTier.SIGNED_IN_BYOK, max_duration_seconds=600, max_file_size_mb=500, long_run_key="acct-1"
)
STANDARD = MediaLimits(tier=MediaTier.STANDARD, max_duration_seconds=180, max_file_size_mb=200)


class _Vault:
    def __init__(self) -> None:
        self.stored: dict[str, str] = {}

    async def store(self, run_id: str, api_key: str) -> None:
        self.stored[run_id] = api_key

    async def take(self, run_id: str):
        return None

    async def close(self) -> None:
        pass


class DistributedLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def _enqueue(self, limits, key=None):
        pool = AsyncMock()
        vault = _Vault()
        queue = RunQueue(Settings(redis_url="redis://x:6379/0"), local_runner=AsyncMock(), key_vault=vault)
        with patch.object(job_queue, "create_pool", AsyncMock(return_value=pool)):
            await queue.enqueue("r1", source_url="https://x.test/v", gemini_api_key=key, limits=limits)
        return pool.enqueue_job.await_args, vault

    async def test_bigger_tier_goes_to_the_long_job_with_its_limits_and_no_key(self) -> None:
        call, vault = await self._enqueue(BIGGER, key="secret-key")
        self.assertEqual(call.args, ("process_long_run", "r1"))
        self.assertEqual(call.kwargs["limits"], BIGGER.to_job_arg())
        self.assertEqual(vault.stored, {"r1": "secret-key"})
        self.assertNotIn("secret-key", repr(call))

    async def test_standard_tier_keeps_the_standard_job(self) -> None:
        call, _ = await self._enqueue(STANDARD)
        self.assertEqual(call.args, ("process_run", "r1"))
        self.assertEqual(call.kwargs["limits"]["max_duration_seconds"], 180)

    async def test_no_limits(self) -> None:
        call, _ = await self._enqueue(None)
        self.assertEqual(call.args[0], "process_run")
        self.assertIsNone(call.kwargs["limits"])


class LocalLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_runner_gets_the_limits_object(self) -> None:
        runner = AsyncMock()
        queue = RunQueue(Settings(redis_url=""), local_runner=runner, key_vault=_Vault())
        await queue.enqueue("r1", source_url="https://x.test/v", limits=BIGGER)
        for task in list(queue._local_tasks):
            await task
        self.assertIs(runner.await_args.kwargs["limits"], BIGGER)


if __name__ == "__main__":
    unittest.main()
