import asyncio
import io
import json
import logging
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


class WorkerDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_job_passes_its_own_timeout_as_the_deadline(self) -> None:
        cases = (
            (worker.process_run, container.settings.worker_job_timeout_seconds),
            (worker.process_long_run, container.settings.long_job_timeout_seconds),
        )
        for job, timeout in cases:
            with self.subTest(job=job.__name__), patch.object(
                container.key_vault, "take", AsyncMock(return_value=None)
            ), patch.object(container.process_run_use_case, "execute", AsyncMock()) as execute:
                before = asyncio.get_running_loop().time()
                await job({}, "r1", source_url="https://x.test/v")
                after = asyncio.get_running_loop().time()
            deadline = execute.await_args.kwargs["deadline"]
            self.assertGreaterEqual(deadline, before + timeout)
            self.assertLessEqual(deadline, after + timeout)


class WorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        root = logging.getLogger()
        arq_logger = logging.getLogger("arq")
        saved = (list(root.handlers), root.level, list(arq_logger.handlers))

        def restore() -> None:
            root.handlers, arq_logger.handlers = saved[0], saved[2]
            root.setLevel(saved[1])

        self.addCleanup(restore)

    async def test_startup_runs_the_shared_validation_and_logs_json(self) -> None:
        # What arq's CLI leaves behind: a plain-text handler on `arq` only.
        logging.getLogger("arq").handlers = [logging.StreamHandler(io.StringIO())]
        with patch.object(worker, "validate_startup", AsyncMock()) as validate:
            await worker.startup({})
        validate.assert_awaited_once_with(container, worker.WORKER)

        stream = io.StringIO()
        logging.getLogger().handlers[0].setStream(stream)
        logging.getLogger("videolens").info("billed as an extra run")
        logging.getLogger("arq.worker").info("job done")
        lines = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual([line["message"] for line in lines], ["billed as an extra run", "job done"])
        self.assertEqual(lines[0]["level"], "INFO")
        self.assertEqual(lines[0]["logger"], "videolens")
        # arq's own handler is gone, so its line is printed once, as JSON.
        self.assertEqual(logging.getLogger("arq").handlers, [])

    async def test_shutdown_closes_the_container_once(self) -> None:
        with patch.object(container, "close", AsyncMock()) as close:
            await worker.shutdown({})
        close.assert_awaited_once_with()


class WorkerSettingsTests(unittest.TestCase):
    def test_completion_wait_comes_from_settings(self) -> None:
        self.assertEqual(
            worker.WorkerSettings.job_completion_wait, container.settings.worker_job_completion_wait_seconds
        )

    def test_long_job_has_its_own_timeout(self) -> None:
        functions = worker.WorkerSettings.functions
        self.assertIs(functions[0], worker.process_run)
        long_job = functions[1]
        self.assertEqual(long_job.name, "process_long_run")
        self.assertEqual(long_job.timeout_s, container.settings.long_job_timeout_seconds)
        self.assertEqual(worker.WorkerSettings.job_timeout, container.settings.worker_job_timeout_seconds)


if __name__ == "__main__":
    unittest.main()
