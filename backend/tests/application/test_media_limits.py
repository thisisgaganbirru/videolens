"""Per-caller media limits ("Level 2", owner decision 2026-11-13): signed in
AND own Gemini key -> the bigger set; everyone else -> the standard one. Plus
the one-long-run-per-account guard and the limits travelling to the worker."""

import unittest
from datetime import datetime, timedelta, timezone

from app.application.create_run import CreateRunUseCase
from app.application.entitlements import EntitlementResolver
from app.application.get_run import RUN_ABANDONED_MESSAGE, GetRunUseCase
from app.application.process_run import BYOK_KEY_EXPIRED_MESSAGE, ProcessRunUseCase
from app.domain.entities import AuthMethod, Principal, RunStatus, VideoAnalysis
from app.domain.entitlements import (
    MediaLimits,
    MediaTier,
    duration_over_limit_message,
    size_over_limit_message,
)
from app.domain.errors import (
    LONG_RUN_IN_PROGRESS_MESSAGE,
    LongRunInProgressError,
    MediaValidationError,
    RunSchedulingError,
)

from .fakes import (
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

MB = 1024 * 1024
ANON = Principal(subject="client:anon-0123456789", authenticated=False)
SIGNED_IN = Principal(subject="user:sub-1", authenticated=True, method=AuthMethod.TOKEN, account_id="acct-1")
SAME_ACCOUNT_KEY = Principal(subject="key:k1", authenticated=True, method=AuthMethod.API_KEY, account_id="acct-1")
OTHER_ACCOUNT = Principal(subject="user:sub-2", authenticated=True, method=AuthMethod.TOKEN, account_id="acct-2")
ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")


def resolver(**overrides) -> EntitlementResolver:
    values = dict(
        max_duration_seconds=180,
        max_file_size_mb=200,
        signed_in_byok_max_duration_seconds=600,
        signed_in_byok_max_file_size_mb=500,
    )
    values.update(overrides)
    return EntitlementResolver(**values)


class EnforcingMedia(FakeMediaProcessor):
    """The fake, but holding each call to the limits it was given, the way
    the real adapters do (their own tests: tests/infrastructure/media)."""

    async def save_upload(self, run_id, upload, limits=None):
        saved = await super().save_upload(run_id, upload, limits)
        if limits is not None and (saved.size_bytes or 0) > limits.max_file_size_bytes:
            raise MediaValidationError(size_over_limit_message(limits))
        return saved

    async def enforce_duration_cap(self, run_id, path, limits=None):
        duration = await super().enforce_duration_cap(run_id, path, limits)
        if limits is not None and duration > limits.max_duration_seconds:
            raise MediaValidationError(duration_over_limit_message(duration, limits))
        return duration


class ResolverTests(unittest.TestCase):
    def test_four_combinations(self) -> None:
        r = resolver()
        self.assertEqual(r.media_limits(ANON, byok=False).tier, MediaTier.STANDARD)
        self.assertEqual(r.media_limits(ANON, byok=True).tier, MediaTier.STANDARD)
        self.assertEqual(r.media_limits(SIGNED_IN, byok=False).tier, MediaTier.STANDARD)
        bigger = r.media_limits(SIGNED_IN, byok=True)
        self.assertEqual(bigger.tier, MediaTier.SIGNED_IN_BYOK)
        self.assertEqual((bigger.max_duration_seconds, bigger.max_file_size_mb), (600, 500))
        # Per account, not per credential.
        self.assertEqual(bigger.long_run_key, "acct-1")
        self.assertEqual(r.media_limits(SAME_ACCOUNT_KEY, byok=True).long_run_key, "acct-1")
        for principal, byok in ((ANON, False), (ANON, True), (SIGNED_IN, False)):
            limits = r.media_limits(principal, byok=byok)
            self.assertEqual((limits.max_duration_seconds, limits.max_file_size_mb), (180, 200))
            self.assertIsNone(limits.long_run_key)

    def test_subject_is_the_slot_key_without_an_account_store(self) -> None:
        bare = Principal(subject="user:sub-9", authenticated=True, method=AuthMethod.TOKEN)
        self.assertEqual(resolver().media_limits(bare, byok=True).long_run_key, "user:sub-9")

    def test_hint_names_what_is_missing(self) -> None:
        r = resolver()
        self.assertEqual(r.media_limits(ANON, byok=False).upgrade_action, "Sign in and add your own Gemini key")
        self.assertEqual(r.media_limits(ANON, byok=True).upgrade_action, "Sign in")
        self.assertEqual(r.media_limits(SIGNED_IN, byok=False).upgrade_action, "Add your own Gemini key")
        self.assertIsNone(r.media_limits(SIGNED_IN, byok=True).upgrade_action)

    def test_bigger_tier_is_never_lower_than_standard(self) -> None:
        r = resolver(signed_in_byok_max_duration_seconds=60, signed_in_byok_max_file_size_mb=50)
        self.assertEqual(r.signed_in_byok.max_duration_seconds, 180)
        self.assertEqual(r.signed_in_byok.max_file_size_mb, 200)
        self.assertFalse(r.has_bigger_tier)
        limits = r.media_limits(SIGNED_IN, byok=True)
        self.assertEqual(limits.tier, MediaTier.STANDARD)
        self.assertIsNone(limits.long_run_key)
        # Nothing bigger to reach, so no hint either.
        self.assertIsNone(r.media_limits(ANON, byok=False).upgrade_action)

    def test_one_value_may_be_floored_alone(self) -> None:
        r = resolver(signed_in_byok_max_file_size_mb=100)
        self.assertEqual((r.signed_in_byok.max_duration_seconds, r.signed_in_byok.max_file_size_mb), (600, 200))

    def test_unset_bigger_values_mean_standard(self) -> None:
        r = EntitlementResolver(max_duration_seconds=180, max_file_size_mb=200)
        self.assertFalse(r.has_bigger_tier)

    def test_is_long(self) -> None:
        r = resolver()
        self.assertFalse(r.is_long(duration_seconds=180, size_bytes=200 * MB))
        self.assertTrue(r.is_long(duration_seconds=181))
        self.assertTrue(r.is_long(size_bytes=200 * MB + 1))
        self.assertFalse(r.is_long())


class MessageAndJobArgTests(unittest.TestCase):
    def test_duration_message_offers_the_bigger_limit_only_when_it_would_fit(self) -> None:
        limits = resolver().media_limits(ANON, byok=False)
        self.assertEqual(
            duration_over_limit_message(240, limits),
            "This video is 4:00 long. The limit is 3:00. "
            "Sign in and add your own Gemini key for videos up to 10:00.",
        )
        self.assertEqual(duration_over_limit_message(900, limits), "This video is 15:00 long. The limit is 3:00.")

    def test_messages_without_a_hint_are_unchanged(self) -> None:
        limits = resolver().standard
        self.assertEqual(duration_over_limit_message(240, limits), "This video is 4:00 long. The limit is 3:00.")
        self.assertEqual(size_over_limit_message(limits), "That file is over the 200MB limit.")

    def test_size_message_hint(self) -> None:
        limits = resolver().media_limits(SIGNED_IN, byok=False)
        self.assertEqual(
            size_over_limit_message(limits),
            "That file is over the 200MB limit. Add your own Gemini key for files up to 500MB.",
        )

    def test_job_arg_round_trip_holds_no_credential(self) -> None:
        limits = resolver().media_limits(SIGNED_IN, byok=True)
        arg = limits.to_job_arg()
        self.assertTrue(all(isinstance(v, (str, int, type(None))) for v in arg.values()))
        self.assertEqual(MediaLimits.from_job_arg(arg), limits)
        self.assertIsNone(MediaLimits.from_job_arg(None))


class _IntakeHarness:
    def _use_case(self, *, guard=None, queue=None, distributed=False):
        self.runs = FakeRunRepository()
        self.media = EnforcingMedia()
        self.queue = queue or FakeJobQueue()
        self.guard = guard or FakeLongRunGuard()
        return CreateRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            queue=self.queue,
            spend_cap=FakeSpendCap(),
            free_runs=FakeFreeRunAllowance(enabled=False),
            device_tokens=FakeDeviceTokens(),
            distributed=distributed,
            entitlements=resolver(),
            long_runs=self.guard,
        )

    async def _upload(self, principal, *, byok, seconds=60.0, size_mb=10.0, use_case=None):
        use_case = use_case or self._use_case()
        self.media.probed_duration = seconds
        self.media.upload_size_bytes = int(size_mb * MB)
        return await use_case.execute(
            principal=principal,
            accept_terms=True,
            file=FakeUploadedFile(),
            url=None,
            gemini_api_key="user-key" if byok else None,
        )



class AdmissionPerTierTests(_IntakeHarness, unittest.IsolatedAsyncioTestCase):
    COMBOS = (
        ("anon", ANON, False, False),
        ("anon+byok", ANON, True, False),
        ("signed-in", SIGNED_IN, False, False),
        ("signed-in+byok", SIGNED_IN, True, True),
    )

    async def test_duration_per_tier(self) -> None:
        for name, principal, byok, bigger in self.COMBOS:
            for seconds in (179, 181, 599, 601):
                with self.subTest(combo=name, seconds=seconds):
                    allowed = seconds <= (600 if bigger else 180)
                    if allowed:
                        run = await self._upload(principal, byok=byok, seconds=seconds)
                        self.assertEqual(run.status, RunStatus.QUEUED)
                    else:
                        with self.assertRaises(MediaValidationError) as caught:
                            await self._upload(principal, byok=byok, seconds=seconds)
                        self.assertIn("The limit is", str(caught.exception))

    async def test_size_per_tier(self) -> None:
        for name, principal, byok, bigger in self.COMBOS:
            for size_mb in (199, 201, 499, 501):
                with self.subTest(combo=name, size_mb=size_mb):
                    allowed = size_mb <= (500 if bigger else 200)
                    if allowed:
                        run = await self._upload(principal, byok=byok, size_mb=size_mb)
                        self.assertEqual(run.status, RunStatus.QUEUED)
                    else:
                        with self.assertRaises(MediaValidationError) as caught:
                            await self._upload(principal, byok=byok, size_mb=size_mb)
                        self.assertIn("MB limit", str(caught.exception))

    async def test_over_limit_message_says_what_would_unlock_it(self) -> None:
        with self.assertRaises(MediaValidationError) as caught:
            await self._upload(ANON, byok=True, seconds=300)
        self.assertEqual(
            str(caught.exception), "This video is 5:00 long. The limit is 3:00. Sign in for videos up to 10:00."
        )
        with self.assertRaises(MediaValidationError) as caught:
            await self._upload(SIGNED_IN, byok=True, seconds=601)
        self.assertEqual(str(caught.exception), "This video is 10:01 long. The limit is 10:00.")

    async def test_limits_reach_every_media_call_and_the_queue_and_the_run(self) -> None:
        use_case = self._use_case()
        await self._upload(SIGNED_IN, byok=True, seconds=30, use_case=use_case)
        bigger = self.media.limits_seen["save_upload"][0]
        self.assertEqual(bigger.tier, MediaTier.SIGNED_IN_BYOK)
        self.assertIs(self.media.limits_seen["enforce_duration_cap"][0], bigger)
        self.assertIs(self.queue.enqueued_limits[0], bigger)
        run_id = self.runs.created_ids[0]
        self.assertEqual(self.runs.runs[run_id].media_tier, "signed_in_byok")

        await use_case.execute(
            principal=ANON, accept_terms=True, file=None, url="https://x.test/v", gemini_api_key=None
        )
        self.assertEqual(self.queue.enqueued_limits[1].tier, MediaTier.STANDARD)
        self.assertEqual(self.runs.runs[self.runs.created_ids[1]].media_tier, "standard")


class LongRunGuardAtIntakeTests(_IntakeHarness, unittest.IsolatedAsyncioTestCase):
    async def test_second_long_upload_is_refused_while_one_is_in_flight(self) -> None:
        use_case = self._use_case()
        await self._upload(SIGNED_IN, byok=True, seconds=400, use_case=use_case)
        first = self.runs.created_ids[0]
        self.assertEqual(self.guard.holders, {"acct-1": first})

        with self.assertRaises(LongRunInProgressError) as caught:
            await self._upload(SIGNED_IN, byok=True, seconds=500, use_case=use_case)
        self.assertEqual(str(caught.exception), LONG_RUN_IN_PROGRESS_MESSAGE)
        # Same account through an API key shares the slot; size counts too.
        with self.assertRaises(LongRunInProgressError):
            await self._upload(SAME_ACCOUNT_KEY, byok=True, size_mb=300, use_case=use_case)
        # Nothing was queued for the refused ones, and their files were cleaned.
        self.assertEqual(len(self.queue.enqueued), 1)
        self.assertEqual(len(self.media.cleaned_up), 2)

    async def test_standard_length_runs_are_unaffected(self) -> None:
        use_case = self._use_case()
        await self._upload(SIGNED_IN, byok=True, seconds=400, use_case=use_case)
        run = await self._upload(SIGNED_IN, byok=True, seconds=170, size_mb=150, use_case=use_case)
        self.assertEqual(run.status, RunStatus.QUEUED)
        # A link's length is unknown at intake: never refused there.
        await use_case.execute(
            principal=SIGNED_IN, accept_terms=True, file=None, url="https://x.test/v", gemini_api_key="k"
        )
        self.assertEqual(len(self.queue.enqueued), 3)
        # Another account is not affected either.
        await self._upload(OTHER_ACCOUNT, byok=True, seconds=400, use_case=use_case)
        self.assertEqual(len(self.guard.holders), 2)

    async def test_a_failed_intake_frees_the_slot(self) -> None:
        queue = FakeJobQueue()
        queue.enqueue_error = RuntimeError("redis down")
        use_case = self._use_case(queue=queue)
        with self.assertRaises(RunSchedulingError):
            await self._upload(SIGNED_IN, byok=True, seconds=400, use_case=use_case)
        self.assertEqual(self.guard.holders, {})


class WorkerLimitsTests(unittest.IsolatedAsyncioTestCase):
    def _use_case(self, guard=None):
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.storage = FakeObjectStore()
        self.guard = guard or FakeLongRunGuard()
        return ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=self.storage,
            analysis=FakeAnalysisEngine(result=ANALYSIS),
            free_runs=FakeFreeRunAllowance(enabled=False),
            entitlements=resolver(),
            long_runs=self.guard,
        )

    async def _run(self, use_case, run_id, limits, **kwargs):
        await self.runs.create(run_id, "user:sub-1")
        await use_case.execute(run_id, limits=limits, **kwargs)
        return self.runs.runs[run_id]

    async def test_link_run_uses_the_admitted_limits_everywhere(self) -> None:
        use_case = self._use_case()
        bigger = resolver().media_limits(SIGNED_IN, byok=True)
        run = await self._run(use_case, "r1", bigger, source_url="https://x.test/v", gemini_api_key="k")
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertIs(self.media.limits_seen["download_url"][0], bigger)
        self.assertIs(self.media.limits_seen["enforce_duration_cap"][0], bigger)

    async def test_caption_fallback_uses_the_runs_limits(self) -> None:
        from app.domain.entities import CaptionTrack

        use_case = self._use_case()
        self.media.download_error = MediaValidationError("blocked")
        self.media.captions = CaptionTrack(text="hi", language="en", automatic=True)
        bigger = resolver().media_limits(SIGNED_IN, byok=True)
        run = await self._run(use_case, "r1", bigger, source_url="https://x.test/v", gemini_api_key="k")
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertIs(self.media.limits_seen["fetch_captions"][0], bigger)

    async def test_no_limits_means_standard_adapter_defaults(self) -> None:
        use_case = self._use_case()
        await self._run(use_case, "r1", None, source_url="https://x.test/v")
        self.assertIsNone(self.media.limits_seen["download_url"][0])

    async def test_long_link_claims_then_releases_the_slot(self) -> None:
        use_case = self._use_case()
        self.media.probed_duration = 400
        bigger = resolver().media_limits(SIGNED_IN, byok=True)
        run = await self._run(use_case, "r1", bigger, source_url="https://x.test/v", gemini_api_key="k")
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertIn(("acct-1", "r1"), self.guard.acquire_calls)
        self.assertEqual(self.guard.holders, {})

    async def test_long_link_fails_while_another_long_run_holds_the_slot(self) -> None:
        guard = FakeLongRunGuard()
        guard.holders["acct-1"] = "other-run"
        use_case = self._use_case(guard)
        self.media.probed_duration = 400
        bigger = resolver().media_limits(SIGNED_IN, byok=True)
        run = await self._run(use_case, "r1", bigger, source_url="https://x.test/v", gemini_api_key="k")
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, LONG_RUN_IN_PROGRESS_MESSAGE)
        self.assertEqual(self.media.normalize_calls, [])
        # The other run's slot is untouched.
        self.assertEqual(guard.holders, {"acct-1": "other-run"})

    async def test_short_link_never_touches_the_slot(self) -> None:
        guard = FakeLongRunGuard()
        guard.holders["acct-1"] = "other-run"
        use_case = self._use_case(guard)
        self.media.probed_duration = 100
        bigger = resolver().media_limits(SIGNED_IN, byok=True)
        run = await self._run(use_case, "r1", bigger, source_url="https://x.test/v", gemini_api_key="k")
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual(guard.acquire_calls, [])

    async def test_uploaded_long_run_keeps_its_intake_slot_and_frees_it_when_done(self) -> None:
        guard = FakeLongRunGuard()
        guard.holders["acct-1"] = "r1"  # taken at intake
        use_case = self._use_case(guard)
        self.media.probed_duration = 400
        bigger = resolver().media_limits(SIGNED_IN, byok=True)
        run = await self._run(use_case, "r1", bigger, source_key="runs/r1/source.mp4", gemini_api_key="k")
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual(guard.holders, {})

    async def test_bigger_tier_never_falls_back_to_the_shared_key(self) -> None:
        # The vault entry expired before the worker took the job.
        use_case = self._use_case()
        bigger = resolver().media_limits(SIGNED_IN, byok=True)
        run = await self._run(use_case, "r1", bigger, source_key="runs/r1/source.mp4", gemini_api_key=None)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, BYOK_KEY_EXPIRED_MESSAGE)
        self.assertEqual(self.media.download_calls, [])
        self.assertEqual(self.storage.deleted, ["runs/r1/source.mp4"])

    async def test_slot_is_freed_when_the_run_fails(self) -> None:
        guard = FakeLongRunGuard()
        use_case = self._use_case(guard)
        self.media.probed_duration = 400
        self.media.normalize_error = MediaValidationError("bad")
        bigger = resolver().media_limits(SIGNED_IN, byok=True)
        run = await self._run(use_case, "r1", bigger, source_url="https://x.test/v", gemini_api_key="k")
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(guard.holders, {})


class StaleThresholdPerTierTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_runs_get_the_longer_threshold(self) -> None:
        runs = FakeRunRepository()
        use_case = GetRunUseCase(runs=runs, stale_after_seconds=720, long_stale_after_seconds=1920)
        old = datetime.now(timezone.utc) - timedelta(seconds=1000)
        for run_id, tier in (("std", "standard"), ("long", "signed_in_byok"), ("legacy", None)):
            run = await runs.create(run_id, "user:sub-1", media_tier=tier)
            run.status = RunStatus.PROCESSING
            run.updated_at = old
        principal = Principal(subject="user:sub-1", authenticated=True, method=AuthMethod.TOKEN)
        self.assertEqual((await use_case.execute("std", principal)).error, RUN_ABANDONED_MESSAGE)
        self.assertEqual((await use_case.execute("legacy", principal)).error, RUN_ABANDONED_MESSAGE)
        self.assertEqual((await use_case.execute("long", principal)).status, RunStatus.PROCESSING)


if __name__ == "__main__":
    unittest.main()
