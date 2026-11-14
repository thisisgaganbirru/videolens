import unittest
from unittest.mock import AsyncMock, patch

from app.container import container
from app.domain.entitlements import MediaLimits, MediaTier
from app.interface.worker import settings as worker

BIGGER = MediaLimits(
    tier=MediaTier.SIGNED_IN_BYOK, max_duration_seconds=600, max_file_size_mb=500, long_run_key="acct-1"
)


class WorkerJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_jobs_hand_the_admitted_limits_to_the_use_case(self) -> None:
        for job in (worker.process_run, worker.process_long_run):
            with self.subTest(job=job.__name__), patch.object(
                container.key_vault, "take", AsyncMock(return_value="k")
            ), patch.object(container.process_run_use_case, "execute", AsyncMock()) as execute:
                await job({}, "r1", source_url="https://x.test/v", limits=BIGGER.to_job_arg())
            self.assertEqual(execute.await_args.kwargs["limits"], BIGGER)
            self.assertEqual(execute.await_args.kwargs["gemini_api_key"], "k")

    async def test_a_job_from_before_limits_existed_gets_standard(self) -> None:
        with patch.object(container.key_vault, "take", AsyncMock(return_value=None)), patch.object(
            container.process_run_use_case, "execute", AsyncMock()
        ) as execute:
            await worker.process_run({}, "r1", source_url="https://x.test/v")
        self.assertIsNone(execute.await_args.kwargs["limits"])


class WorkerSettingsTests(unittest.TestCase):
    def test_long_job_has_its_own_timeout(self) -> None:
        functions = worker.WorkerSettings.functions
        self.assertIs(functions[0], worker.process_run)
        long_job = functions[1]
        self.assertEqual(long_job.name, "process_long_run")
        self.assertEqual(long_job.timeout_s, container.settings.long_job_timeout_seconds)
        self.assertEqual(worker.WorkerSettings.job_timeout, container.settings.worker_job_timeout_seconds)


if __name__ == "__main__":
    unittest.main()
