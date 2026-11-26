"""`POST /api/runs` against the real `DailyBudget` (in-process mode): an
upload refused at intake hands its daily-cap unit back, so it never stands
between the next person and a run (mem/20261120-fix-shared-limit-abuse.md).
The use-case tests count calls on a fake; this one goes through FastAPI and
the adapter's own counter."""

import asyncio
import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from app.application.create_run import CreateRunUseCase
from app.container import container
from app.domain.entities import SavedUpload
from app.domain.errors import MediaValidationError
from app.infrastructure.config import Settings
from app.infrastructure.persistence.run_repository import RunStore
from app.infrastructure.quota.daily_budget import DailyBudget
from app.infrastructure.quota.free_run_allowance import FreeRunAllowanceStore
from app.infrastructure.storage.s3_object_store import S3ObjectStore
from app.interface.api import rate_limiter
from app.interface.api.app import app

SETTINGS = Settings(_env_file=None, gemini_api_key="k", daily_run_cap=1, free_runs_per_device=0)
ANON = {"X-Client-ID": "test-client-0123456789"}


class _Media:
    """Accepts any upload except one named `broken.mp4`; never runs ffmpeg."""

    def __init__(self) -> None:
        self.cleaned_up: list[str] = []

    def create_run_dir(self, run_id: str) -> str:
        return os.path.join("runs", run_id)

    def cleanup_run_dir(self, run_id: str) -> None:
        self.cleaned_up.append(run_id)

    async def save_upload(self, run_id: str, upload, limits=None) -> SavedUpload:
        if upload.filename == "broken.mp4":
            raise MediaValidationError("This file couldn't be read.")
        return SavedUpload(path=os.path.join("runs", run_id, "upload.mp4"), run_dir=os.path.join("runs", run_id))

    async def enforce_duration_cap(self, run_id: str, path: str, limits=None) -> float:
        return 12.0


class _Queue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, run_id: str, **kwargs) -> None:
        self.enqueued.append(run_id)


class IntakeCapRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        rate_limiter.limiter.reset()
        self.addCleanup(rate_limiter.limiter.reset)
        self.budget = DailyBudget(SETTINGS)
        self.media = _Media()
        self.queue = _Queue()
        use_case = CreateRunUseCase(
            runs=RunStore(SETTINGS),
            media=self.media,
            storage=S3ObjectStore(SETTINGS),
            queue=self.queue,
            spend_cap=self.budget,
            free_runs=FreeRunAllowanceStore(SETTINGS),
            device_tokens=container.device_tokens,
            distributed=False,
        )
        patcher = patch.object(container, "create_run_use_case", use_case)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def _upload(self, filename: str):
        return self.client.post(
            "/api/runs",
            headers=ANON,
            data={"accept_terms": "true"},
            files={"file": (filename, b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
        )

    def test_a_rejected_upload_does_not_spend_the_last_unit(self) -> None:
        for _ in range(3):
            refused = self._upload("broken.mp4")
            self.assertEqual(refused.status_code, 400, refused.text)

        accepted = self._upload("clip.mp4")
        self.assertEqual(accepted.status_code, 202, accepted.text)
        self.assertEqual(self.queue.enqueued, [accepted.json()["run_id"]])

        # Now the cap of one is really spent.
        capped = self._upload("clip.mp4")
        self.assertEqual(capped.status_code, 503, capped.text)
        self.assertEqual(len(self.queue.enqueued), 1)

    def test_the_remaining_count_comes_back_after_each_refusal(self) -> None:
        self.assertEqual(asyncio.run(self.budget.remaining()), 1)
        self._upload("broken.mp4")
        self.assertEqual(asyncio.run(self.budget.remaining()), 1)
        self._upload("clip.mp4")
        self.assertEqual(asyncio.run(self.budget.remaining()), 0)


if __name__ == "__main__":
    unittest.main()
