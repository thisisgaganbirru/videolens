import unittest

from app.application.create_run import CreateRunUseCase
from app.domain.entities import AuthMethod, FreeRunPeriod, Principal
from app.domain.errors import (
    DeviceTokenInvalidError,
    FreeRunsExhaustedError,
    InvalidSourceError,
    MediaValidationError,
    QuotaExceededError,
    RunSchedulingError,
    TermsNotAcceptedError,
)

from .fakes import (
    FakeAccountFreeRunAllowance,
    FakeDeviceTokens,
    FakeFreeRunAllowance,
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
        # Free runs off here so these tests keep asserting only what they
        # always did; FreeRunAdmissionTests below turns them on.
        self.free_runs = FakeFreeRunAllowance(enabled=False)
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
            free_runs=self.free_runs,
            device_tokens=FakeDeviceTokens(),
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
        with self.assertRaises(QuotaExceededError) as caught:
            await use_case.execute(
                principal=PRINCIPAL, accept_terms=True, file=None, url="https://x.test/v.mp4", gemini_api_key=None
            )
        # The budget frees at the next UTC midnight: the API sends this as Retry-After.
        self.assertTrue(1 <= caught.exception.retry_after_seconds <= 86400)
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

    async def test_a_url_run_is_recorded_as_a_link_with_no_stored_platform(self) -> None:
        use_case = self._make_use_case()
        run = await use_case.execute(
            principal=PRINCIPAL, accept_terms=True, file=None, url="https://x.test/v", gemini_api_key=None
        )
        stored = self.runs.runs[run.run_id]
        self.assertEqual(stored.source_kind, "link")
        # Link platforms come from yt-dlp metadata at read time, not intake.
        self.assertIsNone(stored.platform)
        self.assertIsNone(stored.duration_seconds)

    async def test_a_video_upload_is_recorded_as_a_file_with_its_probed_duration(self) -> None:
        use_case = self._make_use_case()
        run = await use_case.execute(
            principal=PRINCIPAL, accept_terms=True, file=FakeUploadedFile("my holiday.mov"),
            url=None, gemini_api_key=None,
        )
        stored = self.runs.runs[run.run_id]
        self.assertEqual(stored.source_kind, "file")
        self.assertEqual(stored.platform, "video_file")
        self.assertEqual(stored.duration_seconds, 42.5)

    async def test_an_mp3_upload_is_recorded_as_an_audio_file(self) -> None:
        use_case = self._make_use_case(distributed=True)
        self.media.upload_extension = ".mp3"
        run = await use_case.execute(
            principal=PRINCIPAL, accept_terms=True, file=FakeUploadedFile("Jane Doe voicemail.mp3"),
            url=None, gemini_api_key=None,
        )
        stored = self.runs.runs[run.run_id]
        self.assertEqual(stored.platform, "audio_file")
        # The submitted filename is never written anywhere on the run.
        self.assertNotIn("Jane", stored.model_dump_json())


URL = "https://x.test/v.mp4"


class FreeRunAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def _make(self, *, spend_allowed: bool = True, per_device: int = 3, per_ip: int = 10):
        self.free_runs = FakeFreeRunAllowance(per_device=per_device, per_ip=per_ip)
        self.media = FakeMediaProcessor()
        self.queue = FakeJobQueue()
        self.spend_cap = FakeSpendCap(allow=spend_allowed)
        return CreateRunUseCase(
            runs=FakeRunRepository(),
            media=self.media,
            storage=FakeObjectStore(),
            queue=self.queue,
            spend_cap=self.spend_cap,
            free_runs=self.free_runs,
            device_tokens=FakeDeviceTokens(),
            distributed=False,
        )

    async def _run(self, use_case, *, token="good:dev-a", ip="1.1.1.1", key=None, file=None, url=URL):
        return await use_case.execute(
            principal=PRINCIPAL, accept_terms=True, file=file, url=url,
            gemini_api_key=key, device_token=token, client_ip=ip,
        )

    async def test_own_key_is_exempt_and_needs_no_token(self) -> None:
        use_case = self._make()
        await self._run(use_case, token=None, key="user-key")
        self.assertEqual(self.free_runs.consume_calls, 0)
        self.assertEqual(len(self.queue.enqueued), 1)

    async def test_missing_token_is_rejected_before_any_work(self) -> None:
        use_case = self._make()
        with self.assertRaises(DeviceTokenInvalidError):
            await self._run(use_case, token=None)
        self.assertEqual(self.spend_cap.consume_calls, 0)
        self.assertEqual(self.queue.enqueued, [])

    async def test_forged_token_is_rejected(self) -> None:
        use_case = self._make()
        with self.assertRaises(DeviceTokenInvalidError):
            await self._run(use_case, token="bad:dev-a")

    async def test_device_limit_returns_the_device_numbers(self) -> None:
        use_case = self._make(per_device=2)
        await self._run(use_case)
        await self._run(use_case)
        with self.assertRaises(FreeRunsExhaustedError) as caught:
            await self._run(use_case)
        self.assertEqual((caught.exception.limit, caught.exception.used), (2, 2))
        self.assertEqual(len(self.queue.enqueued), 2)
        self.assertEqual(self.spend_cap.consume_calls, 2)

    async def test_ip_backstop_trips_with_the_device_numbers(self) -> None:
        use_case = self._make(per_device=3, per_ip=2)
        await self._run(use_case, token="good:dev-a")
        await self._run(use_case, token="good:dev-b")
        with self.assertRaises(FreeRunsExhaustedError) as caught:
            await self._run(use_case, token="good:dev-c")
        # A fresh device on the same IP: its own numbers, not the IP's.
        self.assertEqual((caught.exception.limit, caught.exception.used), (3, 0))

    async def test_disabled_feature_ignores_the_token(self) -> None:
        use_case = self._make()
        self.free_runs._enabled = False
        await self._run(use_case, token=None)
        self.assertEqual(self.free_runs.consume_calls, 0)

    async def test_free_run_is_taken_before_the_daily_cap_and_refunded_when_it_rejects(self) -> None:
        use_case = self._make(spend_allowed=False)
        with self.assertRaises(QuotaExceededError):
            await self._run(use_case)
        self.assertEqual(self.free_runs.consume_calls, 1)
        self.assertEqual(self.spend_cap.consume_calls, 1)
        self.assertEqual(len(self.free_runs.refunds), 1)
        self.assertEqual(self.free_runs.device_counts["dev-a"], 0)

    async def test_media_validation_failure_refunds_the_free_run(self) -> None:
        use_case = self._make()
        self.media.enforce_duration_error = MediaValidationError("too long")
        with self.assertRaises(MediaValidationError):
            await self._run(use_case, file=FakeUploadedFile(), url=None)
        self.assertEqual(self.free_runs.device_counts["dev-a"], 0)
        self.assertEqual(self.free_runs.ip_counts["1.1.1.1"], 0)

    async def test_scheduling_failure_refunds_the_free_run(self) -> None:
        use_case = self._make()
        self.queue.enqueue_error = ConnectionError("redis down")
        with self.assertRaises(RunSchedulingError):
            await self._run(use_case)
        self.assertEqual(len(self.free_runs.refunds), 1)

    async def test_an_accepted_run_holds_its_free_run_for_the_pipeline(self) -> None:
        use_case = self._make()
        run = await self._run(use_case)
        self.assertIn(run.run_id, self.free_runs.held)
        self.assertEqual(self.free_runs.held[run.run_id].device_id, "dev-a")

    async def test_a_byok_run_holds_nothing(self) -> None:
        use_case = self._make()
        await self._run(use_case, token=None, key="user-key")
        self.assertEqual(self.free_runs.held, {})

    async def test_a_rejected_intake_drops_the_hold_and_refunds_once(self) -> None:
        use_case = self._make()
        self.queue.enqueue_error = ConnectionError("redis down")
        with self.assertRaises(RunSchedulingError):
            await self._run(use_case)
        self.assertEqual(self.free_runs.held, {})
        self.assertEqual(len(self.free_runs.refunds), 1)

    async def test_invalid_source_is_rejected_before_spending_a_free_run(self) -> None:
        use_case = self._make()
        with self.assertRaises(InvalidSourceError):
            await self._run(use_case, url=None)
        self.assertEqual(self.free_runs.consume_calls, 0)


PERSON = Principal(
    subject="user:sub-1", authenticated=True, method=AuthMethod.TOKEN, account_id="acct-1", workspace_id="ws-1"
)
AGENT = Principal(
    subject="key:key-1", authenticated=True, method=AuthMethod.API_KEY, account_id="acct-1", workspace_id="ws-1"
)
# Signed in on a deployment with no account store: no account id to count.
BARE_USER = Principal(subject="user:sub-2", authenticated=True, method=AuthMethod.TOKEN)


class AccountFreeRunAdmissionTests(unittest.IsolatedAsyncioTestCase):
    """Signed-in free runs (owner decision 2026-11-13): a signed-in account
    without its own key is admitted against its account counter instead of
    the device counter; per UTC day since 2026-11-14."""

    def _make(self, *, spend_allowed: bool = True, limit: int = 10, enabled: bool = True, wired: bool = True):
        self.free_runs = FakeFreeRunAllowance(per_device=3, per_ip=10)
        self.accounts = FakeAccountFreeRunAllowance(limit=limit, enabled=enabled)
        self.media = FakeMediaProcessor()
        self.queue = FakeJobQueue()
        self.spend_cap = FakeSpendCap(allow=spend_allowed)
        return CreateRunUseCase(
            runs=FakeRunRepository(),
            media=self.media,
            storage=FakeObjectStore(),
            queue=self.queue,
            spend_cap=self.spend_cap,
            free_runs=self.free_runs,
            device_tokens=FakeDeviceTokens(),
            distributed=False,
            account_free_runs=self.accounts if wired else None,
        )

    async def _run(self, use_case, *, principal=PERSON, token=None, key=None, file=None, url=URL, ip="1.1.1.1"):
        return await use_case.execute(
            principal=principal, accept_terms=True, file=file, url=url,
            gemini_api_key=key, device_token=token, client_ip=ip,
        )

    async def test_a_signed_in_account_is_admitted_and_counted_without_a_device_token(self) -> None:
        use_case = self._make()
        run = await self._run(use_case, token=None)
        self.assertEqual(self.accounts.used("acct-1"), 1)
        self.assertIn(run.run_id, self.accounts.held)
        # Not additive: the device counter is never touched.
        self.assertEqual(self.free_runs.consume_calls, 0)
        self.assertEqual(self.free_runs.held, {})

    async def test_the_device_counter_is_untouched_even_when_a_token_is_sent(self) -> None:
        use_case = self._make()
        await self._run(use_case, token="good:dev-a")
        self.assertEqual(self.free_runs.device_counts, {})

    async def test_the_eleventh_run_is_refused_with_the_account_numbers(self) -> None:
        use_case = self._make()
        for _ in range(10):
            await self._run(use_case)
        with self.assertRaises(FreeRunsExhaustedError) as caught:
            await self._run(use_case)
        error = caught.exception
        self.assertEqual((error.limit, error.used, error.scope, error.period), (10, 10, "account", "day"))
        self.assertEqual(
            str(error),
            "You have used today's free runs. Add your own Gemini key to keep going, or come back tomorrow.",
        )
        self.assertEqual(set(self.accounts.consume_periods), {FreeRunPeriod.DAY})
        self.assertEqual(len(self.queue.enqueued), 10)
        # Refused before the daily budget is touched.
        self.assertEqual(self.spend_cap.consume_calls, 10)

    async def test_an_api_key_spends_its_owners_account_runs(self) -> None:
        use_case = self._make(limit=2)
        await self._run(use_case, principal=PERSON)
        await self._run(use_case, principal=AGENT)
        with self.assertRaises(FreeRunsExhaustedError):
            await self._run(use_case, principal=AGENT)
        self.assertEqual(self.accounts.used("acct-1"), 2)

    async def test_own_key_is_exempt(self) -> None:
        use_case = self._make()
        await self._run(use_case, key="user-key")
        self.assertEqual(self.accounts.consume_calls, 0)
        self.assertEqual(self.accounts.held, {})

    async def test_anonymous_callers_stay_on_the_device_rule(self) -> None:
        use_case = self._make()
        await self._run(use_case, principal=PRINCIPAL, token="good:dev-a")
        self.assertEqual(self.accounts.consume_calls, 0)
        self.assertEqual(self.free_runs.device_counts["dev-a"], 1)
        with self.assertRaises(DeviceTokenInvalidError):
            await self._run(use_case, principal=PRINCIPAL, token=None)

    async def test_the_device_402_carries_scope_device(self) -> None:
        use_case = self._make()
        for _ in range(3):
            await self._run(use_case, principal=PRINCIPAL, token="good:dev-a")
        with self.assertRaises(FreeRunsExhaustedError) as caught:
            await self._run(use_case, principal=PRINCIPAL, token="good:dev-a")
        self.assertEqual((caught.exception.scope, caught.exception.period), ("device", "day"))

    async def test_disabled_account_allowance_falls_back_to_the_device_rule(self) -> None:
        use_case = self._make(enabled=False)
        with self.assertRaises(DeviceTokenInvalidError):
            await self._run(use_case, token=None)
        await self._run(use_case, token="good:dev-a")
        self.assertEqual(self.free_runs.device_counts["dev-a"], 1)
        self.assertEqual(self.accounts.consume_calls, 0)

    async def test_unwired_account_allowance_falls_back_to_the_device_rule(self) -> None:
        use_case = self._make(wired=False)
        await self._run(use_case, token="good:dev-a")
        self.assertEqual(self.free_runs.device_counts["dev-a"], 1)

    async def test_signed_in_without_an_account_store_uses_the_device_rule(self) -> None:
        use_case = self._make()
        await self._run(use_case, principal=BARE_USER, token="good:dev-a")
        self.assertEqual(self.accounts.consume_calls, 0)
        self.assertEqual(self.free_runs.device_counts["dev-a"], 1)

    async def test_a_rejected_intake_hands_the_account_run_back_once(self) -> None:
        use_case = self._make(spend_allowed=False)
        with self.assertRaises(QuotaExceededError):
            await self._run(use_case)
        self.assertEqual(self.accounts.used("acct-1"), 0)
        self.assertEqual(len(self.accounts.refunds), 1)
        self.assertEqual(self.accounts.held, {})

    async def test_a_media_validation_failure_hands_the_account_run_back(self) -> None:
        use_case = self._make()
        self.media.enforce_duration_error = MediaValidationError("too long")
        with self.assertRaises(MediaValidationError):
            await self._run(use_case, file=FakeUploadedFile(), url=None)
        self.assertEqual(self.accounts.used("acct-1"), 0)

    async def test_a_new_day_starts_a_fresh_allowance(self) -> None:
        use_case = self._make(limit=1)
        await self._run(use_case)
        with self.assertRaises(FreeRunsExhaustedError):
            await self._run(use_case)
        self.accounts.day = "2026-11-15"
        await self._run(use_case)
        self.assertEqual(self.accounts.counts[("acct-1", "2026-11-14")], 1)
        self.assertEqual(self.accounts.counts[("acct-1", "2026-11-15")], 1)
        # The monthly key is not the free plan's counter.
        self.assertNotIn(("acct-1", "2026-11"), self.accounts.counts)


if __name__ == "__main__":
    unittest.main()
