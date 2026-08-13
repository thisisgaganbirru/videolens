import unittest

from app.application.create_run import CreateRunUseCase
from app.domain.entities import Principal
from app.domain.errors import (
    InvalidSourceError,
    MediaValidationError,
    QuotaExceededError,
    RunSchedulingError,
    TermsNotAcceptedError,
)

from .fakes import (
    FakeJobQueue,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
    FakeSpendCap,
    FakeUploadedFile,
)

PRINCIPAL = Principal(subject="client:test-owner", authenticated=False)


class CreateRunUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def _make_use_case(self, *, distributed: bool = False, spend_allowed: bool = True):
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.storage = FakeObjectStore()
        self.queue = FakeJobQueue()
        self.spend_cap = FakeSpendCap(allow=spend_allowed)
        return CreateRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=self.storage,
            queue=self.queue,
            spend_cap=self.spend_cap,
            distributed=distributed,
        )

    async def test_rejects_when_terms_not_accepted(self) -> None:
        use_case = self._make_use_case()
        with self.assertRaises(TermsNotAcceptedError):
            await use_case.execute(
                principal=PRINCIPAL, accept_terms=False, file=None, url="https://x.test/v.mp4", gemini_api_key=None
            )
        self.assertEqual(self.spend_cap.consume_calls, 0)
        self.assertEqual(self.queue.enqueued, [])

    async def test_rejects_when_daily_quota_exceeded(self) -> None:
        use_case = self._make_use_case(spend_allowed=False)
        with self.assertRaises(QuotaExceededError):
            await use_case.execute(
                principal=PRINCIPAL, accept_terms=True, file=None, url="https://x.test/v.mp4", gemini_api_key=None
            )
        self.assertEqual(self.spend_cap.consume_calls, 1)
        self.assertEqual(self.queue.enqueued, [])

    async def test_byok_key_bypasses_the_quota_check_entirely(self) -> None:
        use_case = self._make_use_case(spend_allowed=False)
        run = await use_case.execute(
            principal=PRINCIPAL, accept_terms=True, file=None, url="https://x.test/v.mp4", gemini_api_key="user-key"
        )
        self.assertEqual(self.spend_cap.consume_calls, 0)
        self.assertEqual(self.queue.enqueued[0]["gemini_api_key"], "user-key")
        self.assertEqual(run.status.value, "queued")

    async def test_rejects_when_both_file_and_url_given_and_closes_the_file(self) -> None:
        use_case = self._make_use_case()
        upload = FakeUploadedFile()
        with self.assertRaises(InvalidSourceError):
            await use_case.execute(
                principal=PRINCIPAL,
                accept_terms=True,
                file=upload,
                url="https://x.test/v.mp4",
                gemini_api_key=None,
            )
        self.assertTrue(upload.closed)
        self.assertEqual(self.queue.enqueued, [])

    async def test_rejects_when_neither_file_nor_url_given(self) -> None:
        use_case = self._make_use_case()
        with self.assertRaises(InvalidSourceError):
            await use_case.execute(principal=PRINCIPAL, accept_terms=True, file=None, url=None, gemini_api_key=None)

    async def test_creates_run_from_url_in_local_mode(self) -> None:
        use_case = self._make_use_case(distributed=False)
        run = await use_case.execute(
            principal=PRINCIPAL, accept_terms=True, file=None, url="https://x.test/v.mp4", gemini_api_key=None
        )
        self.assertEqual(self.runs.created_ids, [run.run_id])
        enqueued = self.queue.enqueued[0]
        self.assertEqual(enqueued["run_id"], run.run_id)
        self.assertIsNone(enqueued["saved_path"])
        self.assertIsNone(enqueued["run_dir"])
        self.assertEqual(enqueued["source_url"], "https://x.test/v.mp4")
        self.assertIsNone(enqueued["source_key"])
        self.assertEqual(self.storage.uploaded, {})

    async def test_creates_run_from_file_upload_in_local_mode(self) -> None:
        use_case = self._make_use_case(distributed=False)
        upload = FakeUploadedFile()
        run = await use_case.execute(
            principal=PRINCIPAL, accept_terms=True, file=upload, url=None, gemini_api_key=None
        )
        self.assertEqual(len(self.media.enforced_duration), 1)
        # Local mode: no S3 upload, and the temp dir is left in place for the
        # in-process worker to pick up - only failures clean it up here.
        self.assertEqual(self.storage.uploaded, {})
        self.assertEqual(self.media.cleaned_up, [])
        enqueued = self.queue.enqueued[0]
        self.assertEqual(enqueued["saved_path"], f"/tmp/{run.run_id}/upload.mp4")
        self.assertEqual(enqueued["run_dir"], f"/tmp/{run.run_id}")
        self.assertIsNone(enqueued["source_key"])

    async def test_creates_run_from_file_upload_in_distributed_mode(self) -> None:
        use_case = self._make_use_case(distributed=True)
        upload = FakeUploadedFile()
        run = await use_case.execute(
            principal=PRINCIPAL, accept_terms=True, file=upload, url=None, gemini_api_key=None
        )
        # Distributed mode: uploaded to S3 and the local copy is dropped
        # immediately, since a different process (the worker) handles it.
        self.assertEqual(self.storage.uploaded[run.run_id], f"runs/{run.run_id}/source.mp4")
        self.assertEqual(self.media.cleaned_up, [run.run_id])
        enqueued = self.queue.enqueued[0]
        self.assertIsNone(enqueued["saved_path"])
        self.assertIsNone(enqueued["run_dir"])
        self.assertEqual(enqueued["source_key"], f"runs/{run.run_id}/source.mp4")

    async def test_media_validation_error_cleans_up_and_propagates_unwrapped(self) -> None:
        use_case = self._make_use_case()
        self.media.enforce_duration_error = MediaValidationError("too long")
        upload = FakeUploadedFile()
        with self.assertRaises(MediaValidationError):
            await use_case.execute(principal=PRINCIPAL, accept_terms=True, file=upload, url=None, gemini_api_key=None)
        self.assertEqual(len(self.media.cleaned_up), 1)
        self.assertEqual(self.storage.deleted, [])
        self.assertEqual(self.queue.enqueued, [])

    async def test_unexpected_enqueue_failure_is_wrapped_and_deletes_uploaded_source(self) -> None:
        use_case = self._make_use_case(distributed=True)
        self.queue.enqueue_error = ConnectionError("redis down")
        upload = FakeUploadedFile()
        with self.assertRaises(RunSchedulingError):
            await use_case.execute(principal=PRINCIPAL, accept_terms=True, file=upload, url=None, gemini_api_key=None)
        self.assertEqual(len(self.storage.deleted), 1)
        self.assertEqual(len(self.media.cleaned_up), 2)  # once after S3 upload, once in the except block


if __name__ == "__main__":
    unittest.main()
