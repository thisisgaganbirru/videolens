"""A run admitted on the caller's own Gemini key never runs on the shared key.

BYOK runs skip the free-run and daily-cap checks at intake. Their key reaches
the worker only through the single-use vault (15-minute TTL), so a run that
waited past it, or an arq retry after the first attempt took the key, used to
fall back to the shared key silently. Intake now records `admitted_byok` on
the run and the worker fails such a run when it has no key.
"""

import asyncio
import unittest

from app.application.create_run import CreateRunUseCase
from app.application.entitlements import EntitlementResolver
from app.application.process_run import (
    BYOK_KEY_EXPIRED_MESSAGE,
    RUN_INTERRUPTED_MESSAGE,
    ProcessRunUseCase,
)
from app.domain.entities import AuthMethod, CaptionTrack, Principal, RunStatus, VideoAnalysis
from app.domain.entitlements import MediaTier
from app.domain.errors import MediaValidationError, OwnKeyUnavailableError
from app.infrastructure.byok.key_vault import ByokKeyStore
from app.infrastructure.config import Settings
from app.infrastructure.queue.job_queue import RunQueue

from .fakes import (
    FakeAccountFreeRunAllowance,
    FakeAnalysisEngine,
    FakeDeviceTokens,
    FakeFreeRunAllowance,
    FakeJobQueue,
    FakeLongRunGuard,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
    FakeSpendCap,
    FakeUploadedFile,
)

ANON = Principal(subject="client:anon-0123456789", authenticated=False)
SIGNED_IN = Principal(subject="user:sub-1", authenticated=True, method=AuthMethod.TOKEN, account_id="acct-1")
ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")


def resolver(*, bigger: bool = True) -> EntitlementResolver:
    return EntitlementResolver(
        max_duration_seconds=180,
        max_file_size_mb=200,
        signed_in_byok_max_duration_seconds=600 if bigger else 180,
        signed_in_byok_max_file_size_mb=500 if bigger else 200,
    )


class ExpiredKeyTests(unittest.IsolatedAsyncioTestCase):
    """Intake through CreateRunUseCase (distributed, so the key would go to the
    vault), then the worker's use case with what an expired vault returns."""

    def setUp(self) -> None:
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.storage = FakeObjectStore()
        self.queue = FakeJobQueue()
        self.spend_cap = FakeSpendCap()
        self.free_runs = FakeFreeRunAllowance(enabled=True)
        self.account_free_runs = FakeAccountFreeRunAllowance(enabled=True)
        self.analysis = FakeAnalysisEngine(result=ANALYSIS)
        self.guard = FakeLongRunGuard()

    def _intake(self, entitlements: EntitlementResolver) -> CreateRunUseCase:
        return CreateRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=self.storage,
            queue=self.queue,
            spend_cap=self.spend_cap,
            free_runs=self.free_runs,
            device_tokens=FakeDeviceTokens(),
            distributed=True,
            account_free_runs=self.account_free_runs,
            entitlements=entitlements,
            long_runs=self.guard,
        )

    def _worker(self, entitlements: EntitlementResolver) -> ProcessRunUseCase:
        return ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=self.storage,
            analysis=self.analysis,
            free_runs=self.free_runs,
            account_free_runs=self.account_free_runs,
            entitlements=entitlements,
            long_runs=self.guard,
        )

    async def _admit_and_work(
        self, principal, *, url=None, file=None, key="byok", vault_key=None, entitlements=None
    ):
        entitlements = entitlements or resolver()
        run = await self._intake(entitlements).execute(
            principal=principal,
            accept_terms=True,
            file=file,
            url=url,
            gemini_api_key=key,
            device_token="good:device-1",
            client_ip="203.0.113.9",
        )
        job = self.queue.enqueued[-1]
        limits = self.queue.enqueued_limits[-1]
        # The worker reads the key from the vault: `vault_key` is what take() gave.
        await self._worker(entitlements).execute(
            run.run_id,
            source_url=job["source_url"],
            source_key=job["source_key"],
            gemini_api_key=vault_key,
            limits=limits,
        )
        return self.runs.runs[run.run_id], limits

    def _assert_never_reached_gemini(self) -> None:
        self.assertEqual(self.analysis.calls, [])
        self.assertEqual(self.analysis.caption_calls, [])
        self.assertEqual(self.media.download_calls, [])
        self.assertEqual(self.media.normalize_calls, [])

    def _assert_nothing_was_counted(self) -> None:
        # Own-key intake takes nothing, so there is nothing to hand back twice.
        self.assertEqual(self.spend_cap.consume_calls, 0)
        self.assertEqual(self.free_runs.consume_calls, 0)
        self.assertEqual(self.account_free_runs.consume_calls, 0)
        self.assertEqual(self.free_runs.refunds, [])
        self.assertEqual(self.account_free_runs.refunds, [])

    async def test_intake_records_the_flag_but_never_the_key(self) -> None:
        run = await self._intake(resolver()).execute(
            principal=ANON, accept_terms=True, file=None, url="https://x.test/v",
            gemini_api_key="byok-secret", device_token=None,
        )
        stored = self.runs.runs[run.run_id]
        self.assertTrue(stored.admitted_byok)
        self.assertNotIn("byok-secret", stored.model_dump_json())

    async def test_intake_without_a_key_records_no_flag(self) -> None:
        run = await self._intake(resolver()).execute(
            principal=ANON, accept_terms=True, file=None, url="https://x.test/v",
            gemini_api_key=None, device_token="good:device-1",
        )
        self.assertFalse(self.runs.runs[run.run_id].admitted_byok)

    async def test_anonymous_link_with_expired_key_fails_and_never_uses_the_shared_key(self) -> None:
        run, limits = await self._admit_and_work(ANON, url="https://x.test/v")
        self.assertIs(limits.tier, MediaTier.STANDARD)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, BYOK_KEY_EXPIRED_MESSAGE)
        self._assert_never_reached_gemini()
        self._assert_nothing_was_counted()

    async def test_anonymous_upload_with_expired_key_fails_and_deletes_the_source(self) -> None:
        run, _ = await self._admit_and_work(ANON, file=FakeUploadedFile("clip.mp4"))
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, BYOK_KEY_EXPIRED_MESSAGE)
        self._assert_never_reached_gemini()
        self.assertEqual(self.storage.deleted, [f"runs/{run.run_id}/source.mp4"])

    async def test_signed_in_standard_limit_byok_with_expired_key_fails(self) -> None:
        # No bigger tier configured: a signed-in key holder is on the standard
        # limits, so only the run-record flag can say it was an own-key run.
        run, limits = await self._admit_and_work(
            SIGNED_IN, url="https://x.test/v", entitlements=resolver(bigger=False)
        )
        self.assertIs(limits.tier, MediaTier.STANDARD)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, BYOK_KEY_EXPIRED_MESSAGE)
        self._assert_never_reached_gemini()
        self._assert_nothing_was_counted()

    async def test_signed_in_byok_without_entitlements_wiring_fails(self) -> None:
        # Older wiring (no resolver): limits None, the flag alone decides.
        self.free_runs = FakeFreeRunAllowance(enabled=False)
        run = await CreateRunUseCase(
            runs=self.runs, media=self.media, storage=self.storage, queue=self.queue,
            spend_cap=self.spend_cap, free_runs=self.free_runs,
            device_tokens=FakeDeviceTokens(), distributed=True,
        ).execute(
            principal=SIGNED_IN, accept_terms=True, file=None, url="https://x.test/v",
            gemini_api_key="byok", device_token=None,
        )
        worker = ProcessRunUseCase(
            runs=self.runs, media=self.media, storage=self.storage,
            analysis=self.analysis, free_runs=self.free_runs,
        )
        await worker.execute(run.run_id, source_url="https://x.test/v", gemini_api_key=None, limits=None)
        self.assertEqual(self.runs.runs[run.run_id].error, BYOK_KEY_EXPIRED_MESSAGE)
        self._assert_never_reached_gemini()

    async def test_signed_in_bigger_tier_still_fails_and_frees_its_slot(self) -> None:
        self.guard.holders["acct-1"] = "placeholder"
        run, limits = await self._admit_and_work(SIGNED_IN, url="https://x.test/v")
        self.assertIs(limits.tier, MediaTier.SIGNED_IN_BYOK)
        self.assertEqual(run.error, BYOK_KEY_EXPIRED_MESSAGE)
        self._assert_never_reached_gemini()
        # Release is compare-and-delete per run: another run's slot is untouched,
        # and the refusal path released once (the pipeline's finally never ran).
        self.assertEqual(self.guard.holders, {"acct-1": "placeholder"})

    async def test_byok_with_its_key_still_runs_on_that_key(self) -> None:
        run, _ = await self._admit_and_work(ANON, url="https://x.test/v", vault_key="byok")
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual([key for _, key in self.analysis.calls], ["byok"])

    async def test_caption_fallback_of_a_byok_run_uses_its_key(self) -> None:
        self.media.download_error = MediaValidationError("blocked")
        self.media.captions = CaptionTrack(text="hi", language="en", automatic=True)
        run, _ = await self._admit_and_work(ANON, url="https://x.test/v", vault_key="byok")
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual(len(self.analysis.caption_calls), 1)
        self.assertEqual(self.analysis.calls, [])

    async def test_non_byok_run_is_unchanged_and_uses_the_shared_key(self) -> None:
        run, _ = await self._admit_and_work(ANON, url="https://x.test/v", key=None)
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertFalse(run.admitted_byok)
        # None = the engine's shared key.
        self.assertEqual([key for _, key in self.analysis.calls], [None])
        self.assertEqual(self.free_runs.consume_calls, 1)
        self.assertEqual(self.spend_cap.consume_calls, 1)

    async def test_retry_after_the_first_attempt_took_the_key_says_interrupted(self) -> None:
        # arq re-runs a job whose worker died mid-run (max_tries=2); the vault
        # entry was deleted by the first attempt's take().
        run = await self.runs.create("r1", ANON.subject, admitted_byok=True)
        run.status = RunStatus.PROCESSING
        await self._worker(resolver()).execute("r1", source_url="https://x.test/v", gemini_api_key=None)
        self.assertEqual(self.runs.runs["r1"].status, RunStatus.FAILED)
        self.assertEqual(self.runs.runs["r1"].error, RUN_INTERRUPTED_MESSAGE)
        self._assert_never_reached_gemini()

    async def test_retry_of_a_finished_run_leaves_its_outcome(self) -> None:
        for status, error in ((RunStatus.COMPLETE, None), (RunStatus.FAILED, "earlier message")):
            with self.subTest(status=status):
                run = await self.runs.create(f"r-{status.value}", ANON.subject, admitted_byok=True)
                run.status = status
                run.error = error
                await self._worker(resolver()).execute(run.run_id, source_url="https://x.test/v")
                self.assertEqual(self.runs.runs[run.run_id].status, status)
                self.assertEqual(self.runs.runs[run.run_id].error, error)
        self._assert_never_reached_gemini()

    async def test_a_run_with_no_record_left_is_not_started(self) -> None:
        await self._worker(resolver()).execute("gone", source_url="https://x.test/v", gemini_api_key=None)
        self._assert_never_reached_gemini()
        self.assertNotIn("gone", self.runs.runs)


class OwnKeyUnavailableErrorTests(unittest.TestCase):
    def test_message_is_for_the_phone_and_detail_for_the_operator(self) -> None:
        for started, message in ((False, BYOK_KEY_EXPIRED_MESSAGE), (True, RUN_INTERRUPTED_MESSAGE)):
            exc = OwnKeyUnavailableError(started=started)
            self.assertEqual(str(exc), message)
            self.assertIn("GEMINI_API_KEY", exc.log_detail)
            self.assertNotIn("vault", str(exc))


class LocalModeTests(unittest.IsolatedAsyncioTestCase):
    """Local (non-distributed) mode: the key goes straight to the in-process
    runner and never through the vault, so it cannot expire in a queue."""

    async def test_local_byok_run_uses_its_own_key_end_to_end(self) -> None:
        settings = Settings(redis_url="")
        runs = FakeRunRepository()
        media = FakeMediaProcessor()
        storage = FakeObjectStore(enabled=False)
        analysis = FakeAnalysisEngine(result=ANALYSIS)
        free_runs = FakeFreeRunAllowance(enabled=False)
        vault = ByokKeyStore(settings)
        worker = ProcessRunUseCase(runs=runs, media=media, storage=storage, analysis=analysis, free_runs=free_runs)
        queue = RunQueue(settings, local_runner=worker.execute, key_vault=vault)
        intake = CreateRunUseCase(
            runs=runs, media=media, storage=storage, queue=queue, spend_cap=FakeSpendCap(),
            free_runs=free_runs, device_tokens=FakeDeviceTokens(), distributed=False,
        )
        run = await intake.execute(
            principal=ANON, accept_terms=True, file=None, url="https://x.test/v",
            gemini_api_key="byok", device_token=None,
        )
        await asyncio.gather(*list(queue._local_tasks))
        self.assertTrue(runs.runs[run.run_id].admitted_byok)
        self.assertEqual(runs.runs[run.run_id].status, RunStatus.COMPLETE)
        self.assertEqual([key for _, key in analysis.calls], ["byok"])
        # The in-process dict was never used for it.
        self.assertEqual(vault._memory, {})

    async def test_in_process_vault_is_single_use(self) -> None:
        vault = ByokKeyStore(Settings(redis_url=""))
        await vault.store("r1", "byok")
        self.assertEqual(await vault.take("r1"), "byok")
        self.assertIsNone(await vault.take("r1"))

    async def test_local_runner_with_no_key_refuses_a_byok_run(self) -> None:
        # Same use case in both modes: if a local run ever reached it with no
        # key, the record's flag would still stop it.
        runs = FakeRunRepository()
        analysis = FakeAnalysisEngine(result=ANALYSIS)
        await runs.create("r1", ANON.subject, admitted_byok=True)
        worker = ProcessRunUseCase(
            runs=runs, media=FakeMediaProcessor(), storage=FakeObjectStore(enabled=False),
            analysis=analysis, free_runs=FakeFreeRunAllowance(enabled=False),
        )
        await worker.execute("r1", saved_path="/tmp/x.mp4", run_dir="/tmp", gemini_api_key=None)
        self.assertEqual(runs.runs["r1"].error, BYOK_KEY_EXPIRED_MESSAGE)
        self.assertEqual(analysis.calls, [])


if __name__ == "__main__":
    unittest.main()
