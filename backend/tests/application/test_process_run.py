import asyncio
import os
import unittest

from app.application.create_run import CreateRunUseCase
from app.application.process_run import RUN_INTERRUPTED_MESSAGE, ProcessRunUseCase
from app.domain.entities import (
    AnalysisCompleteness,
    CaptionTrack,
    Principal,
    MediaVisuals,
    RunStatus,
    SourceMetadata,
    VideoAnalysis,
)
from app.domain.errors import (
    AnalysisUnavailableError,
    GeminiConfigurationError,
    MediaValidationError,
)

from .fakes import (
    FakeAccountFreeRunAllowance,
    FakeAnalysisEngine,
    FakeDeviceTokens,
    FakeFreeRunAllowance,
    FakeJobQueue,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
    FakeSpendCap,
    FakeUploadedFile,
    RaisingObjectStore,
)

ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")
CAPTIONS = CaptionTrack(
    text="hello world",
    language="en",
    automatic=True,
    metadata=SourceMetadata(platform="Youtube", source_url="https://x.test/v", title="Clip"),
)


class ProcessRunUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def _make_use_case(self, *, storage=None, analysis=None):
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.storage = storage or FakeObjectStore()
        self.analysis = analysis or FakeAnalysisEngine(result=ANALYSIS)
        self.free_runs = FakeFreeRunAllowance()
        return ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=self.storage,
            analysis=self.analysis,
            free_runs=self.free_runs,
        )

    async def asyncSetUp(self) -> None:
        self.use_case = self._make_use_case()
        await self.runs.create("run-1", "client:owner")

    async def test_processes_source_key_by_downloading_from_object_store(self) -> None:
        await self.use_case.execute("run-1", source_key="runs/run-1/source.mp4")

        expected_path = os.path.join("/tmp/run-1", "source.mp4")
        self.assertEqual(self.storage.downloaded, [("runs/run-1/source.mp4", expected_path)])
        self.assertEqual(len(self.media.enforced_duration), 1)
        self.assertEqual(len(self.media.normalize_calls), 1)
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)
        self.assertEqual(self.runs.runs["run-1"].result, ANALYSIS)
        self.assertEqual(self.storage.deleted, ["runs/run-1/source.mp4"])
        self.assertEqual(self.media.cleaned_up, ["run-1"])

    async def test_processes_source_url_by_downloading_via_media_processor(self) -> None:
        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")

        self.assertEqual(self.media.download_calls, [("run-1", "https://x.test/v.mp4")])
        self.assertEqual(len(self.media.enforced_duration), 1)
        self.assertEqual(self.runs.runs["run-1"].stage, "analyzing")
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)
        # No object-storage key was involved, so nothing to delete.
        self.assertEqual(self.storage.deleted, [])
        self.assertEqual(self.media.cleaned_up, ["run-1"])

    async def test_persists_source_metadata_when_the_media_processor_returns_it(self) -> None:
        self.use_case = self._make_use_case()
        await self.runs.create("run-1", "client:owner")
        self.media.download_metadata = SourceMetadata(
            platform="Instagram", source_url="https://x.test/v.mp4", title="Clip"
        )

        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")

        self.assertEqual(self.runs.runs["run-1"].source_metadata, self.media.download_metadata)

    async def test_passes_source_metadata_to_the_analysis_engine(self) -> None:
        self.media.download_metadata = SourceMetadata(
            platform="YouTube", source_url="https://x.test/v.mp4", title="Clip"
        )

        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")

        self.assertEqual(self.analysis.metadata_seen, [self.media.download_metadata])

    async def test_analyzes_uploads_without_any_source_metadata(self) -> None:
        await self.use_case.execute("run-1", saved_path="/tmp/run-1/upload.mp4", run_dir="/tmp/run-1")

        self.assertEqual(self.analysis.metadata_seen, [None])

    async def test_analyzes_without_metadata_when_the_download_returns_none(self) -> None:
        self.media.download_metadata = None

        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")

        self.assertEqual(self.analysis.metadata_seen, [None])

    async def test_falls_back_to_captions_when_every_download_route_fails(self) -> None:
        self.media.download_error = MediaValidationError("HTTP Error 403: Forbidden")
        self.media.captions = CAPTIONS

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual(run.completeness, AnalysisCompleteness.CAPTIONS_ONLY)
        self.assertEqual(self.analysis.caption_calls, [CAPTIONS])
        self.assertEqual(run.stage, "analyzing_captions")
        # The media path was never reached, so nothing was normalized.
        self.assertEqual(self.media.normalize_calls, [])
        self.assertEqual(self.media.cleaned_up, ["run-1"])

    async def test_a_successful_analysis_is_marked_full(self) -> None:
        await self.use_case.execute("run-1", source_url="https://x.test/v")

        self.assertEqual(self.runs.runs["run-1"].completeness, AnalysisCompleteness.FULL)

    async def test_never_looks_for_captions_when_the_download_succeeds(self) -> None:
        await self.use_case.execute("run-1", source_url="https://x.test/v")

        self.assertEqual(self.media.caption_calls, [])

    async def test_reports_the_download_error_when_no_captions_exist(self) -> None:
        self.media.download_error = MediaValidationError("HTTP Error 403: Forbidden")
        self.media.captions = None

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, "HTTP Error 403: Forbidden")

    async def test_a_broken_caption_fetch_does_not_replace_the_download_diagnosis(self) -> None:
        # The caption attempt is a bonus. Its own failure must not become the
        # explanation the user reads - that would hide why the download failed.
        self.media.download_error = MediaValidationError("Configure cookies for Instagram.")
        self.media.captions_error = RuntimeError("subtitle endpoint exploded")

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, "Configure cookies for Instagram.")

    async def test_a_failing_caption_analysis_also_falls_back_to_the_download_error(self) -> None:
        self.media.download_error = MediaValidationError("HTTP Error 403: Forbidden")
        self.media.captions = CAPTIONS
        self.analysis.caption_error = RuntimeError("gemini refused")

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        self.assertEqual(self.runs.runs["run-1"].error, "HTTP Error 403: Forbidden")

    async def test_persists_metadata_recovered_alongside_the_captions(self) -> None:
        self.media.download_error = MediaValidationError("HTTP Error 403: Forbidden")
        self.media.captions = CAPTIONS

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        self.assertEqual(self.runs.runs["run-1"].source_metadata, CAPTIONS.metadata)

    async def test_uploads_never_attempt_the_caption_fallback(self) -> None:
        self.media.captions = CAPTIONS
        self.analysis.error = MediaValidationError("normalize blew up")

        await self.use_case.execute("run-1", saved_path="/tmp/run-1/upload.mp4", run_dir="/tmp/run-1")

        # There is no URL to fetch captions from; the run just fails.
        self.assertEqual(self.media.caption_calls, [])
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.FAILED)

    async def test_a_cancelled_job_marks_the_run_failed_and_still_cancels(self) -> None:
        # arq cancels the coroutine on job_timeout. CancelledError is a
        # BaseException, so without an explicit branch the run would sit in
        # PROCESSING until its TTL expired.
        self.analysis.error = asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, RUN_INTERRUPTED_MESSAGE)
        # Cleanup still ran despite the cancellation propagating.
        self.assertEqual(self.media.cleaned_up, ["run-1"])

    async def test_uses_a_pre_saved_path_directly_without_re_validating_duration(self) -> None:
        await self.use_case.execute("run-1", saved_path="/tmp/run-1/upload.mp4", run_dir="/tmp/run-1")

        # Local-mode uploads already had their duration enforced synchronously
        # by CreateRunUseCase before being enqueued - this path must not redo it.
        self.assertEqual(self.media.enforced_duration, [])
        self.assertEqual(self.media.normalize_calls, [("/tmp/run-1/upload.mp4", "/tmp/run-1")])
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)

    async def test_sets_error_when_no_source_is_provided_at_all(self) -> None:
        await self.use_case.execute("run-1")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, "No media source was provided.")
        self.assertEqual(self.media.cleaned_up, ["run-1"])

    async def test_media_validation_error_during_download_sets_its_own_message_as_the_error(self) -> None:
        self.media.download_error = MediaValidationError("Media is 400s long, which exceeds the limit.")
        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, "Media is 400s long, which exceeds the limit.")

    async def test_gemini_configuration_error_sets_its_own_message_as_the_error(self) -> None:
        use_case = self._make_use_case(analysis=FakeAnalysisEngine(error=GeminiConfigurationError("no api key configured")))
        await self.runs.create("run-2", "client:owner")
        await use_case.execute("run-2", saved_path="/tmp/run-2/upload.mp4", run_dir="/tmp/run-2")

        run = self.runs.runs["run-2"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, "no api key configured")

    async def test_log_detail_is_never_stored_on_the_run(self) -> None:
        """The whole point of the two-field error: `log_detail` carries the
        operator's half (a config key, a library's stderr) and must stop at the
        log. Storing it would put it straight back on the caller's screen."""
        self.media.download_error = MediaValidationError(
            "This link couldn't be downloaded.",
            log_detail="YTDLP_COOKIES_FILE points at '/srv/cookies.txt', which does not exist.",
        )
        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, "This link couldn't be downloaded.")
        self.assertNotIn("YTDLP_COOKIES_FILE", run.error)

    async def test_transient_analysis_failure_keeps_its_own_message(self) -> None:
        """A busy model is not a bad file, so it must not fall through to the
        generic catch-all - the caller is told to wait, not to re-pick media."""
        use_case = self._make_use_case(
            analysis=FakeAnalysisEngine(
                error=AnalysisUnavailableError(
                    "Gemini is busy right now. This usually clears within a minute.",
                    log_detail="ServerError: 503 UNAVAILABLE",
                )
            )
        )
        await self.runs.create("run-4", "client:owner")
        await use_case.execute("run-4", saved_path="/tmp/run-4/upload.mp4", run_dir="/tmp/run-4")

        run = self.runs.runs["run-4"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(
            run.error, "Gemini is busy right now. This usually clears within a minute."
        )
        self.assertNotIn("503", run.error)

    async def test_unexpected_exception_is_masked_with_a_generic_error_message(self) -> None:
        use_case = self._make_use_case(analysis=FakeAnalysisEngine(error=RuntimeError("stack trace with secrets")))
        await self.runs.create("run-3", "client:owner")
        await use_case.execute("run-3", saved_path="/tmp/run-3/upload.mp4", run_dir="/tmp/run-3")

        run = self.runs.runs["run-3"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, "The analysis didn't finish. Please try again.")
        self.assertNotIn("secrets", run.error)

    async def test_cleanup_still_runs_even_if_deleting_the_source_object_fails(self) -> None:
        use_case = self._make_use_case(storage=RaisingObjectStore())
        await self.runs.create("run-4", "client:owner")

        # Must not raise, even though delete_source() blows up internally.
        await use_case.execute("run-4", source_key="runs/run-4/source.mp4")

        self.assertEqual(self.runs.runs["run-4"].status, RunStatus.COMPLETE)
        self.assertEqual(self.media.cleaned_up, ["run-4"])

    async def test_on_stage_callback_relays_every_stage_through_to_the_run_repository(self) -> None:
        stages: list[str] = []
        original_set_stage = self.runs.set_stage

        async def tracking_set_stage(run_id: str, stage: str) -> None:
            stages.append(stage)
            await original_set_stage(run_id, stage)

        self.runs.set_stage = tracking_set_stage  # type: ignore[method-assign]

        await self.use_case.execute("run-1", source_url="https://x.test/v.mp4")

        self.assertEqual(stages, ["downloading", "normalizing", "uploading_to_gemini", "analyzing"])

    async def test_persists_the_probed_duration_of_a_downloaded_url(self) -> None:
        self.media.probed_duration = 61.0
        await self.use_case.execute("run-1", source_url="https://x.test/v")

        self.assertEqual(self.runs.runs["run-1"].duration_seconds, 61.0)

    async def test_persists_the_probed_duration_of_an_object_store_source(self) -> None:
        self.media.probed_duration = 12.25
        await self.use_case.execute("run-1", source_key="runs/run-1/source.mp4")

        self.assertEqual(self.runs.runs["run-1"].duration_seconds, 12.25)

    async def test_a_caption_recovery_keeps_the_duration_yt_dlp_reported(self) -> None:
        self.media.download_error = MediaValidationError("HTTP Error 403: Forbidden")
        self.media.captions = CaptionTrack(
            text="hi", language="en", automatic=False, duration_seconds=95.0
        )

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual(run.duration_seconds, 95.0)

    async def test_a_failed_duration_write_does_not_fail_the_run(self) -> None:
        async def broken(run_id: str, duration_seconds: float) -> None:
            raise RuntimeError("redis blip")

        self.runs.set_duration = broken  # type: ignore[method-assign]
        await self.use_case.execute("run-1", source_url="https://x.test/v")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertIsNone(run.duration_seconds)

    # --- Phase 5a: history poster (thumbnail + display size) ---

    async def test_link_run_records_visuals_before_it_is_marked_complete(self) -> None:
        self.media.download_thumbnail_urls = ("https://i.test/t.jpg",)
        self.media.download_dims = (1920, 1080)
        self.media.probed_duration = 30.0

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual(run.thumbnail, "data:image/jpeg;base64,AAAA")
        self.assertEqual((run.width, run.height), (1280, 720))
        self.assertEqual(self.runs.visuals_written_while, [RunStatus.PROCESSING])
        self.assertEqual(
            self.media.visuals_calls,
            [
                dict(
                    media_path="/tmp/run-1/download.mp4",
                    thumbnail_urls=("https://i.test/t.jpg",),
                    width=1920,
                    height=1080,
                    duration_seconds=30.0,
                )
            ],
        )

    async def test_object_store_upload_gets_a_frame_grab(self) -> None:
        await self.use_case.execute("run-1", source_key="runs/run-1/source.mp4")

        self.assertEqual(
            self.media.visuals_calls,
            [dict(media_path=os.path.join("/tmp/run-1", "source.mp4"), duration_seconds=42.5)],
        )
        self.assertEqual(self.runs.runs["run-1"].width, 1280)

    async def test_local_upload_gets_a_frame_grab(self) -> None:
        await self.use_case.execute("run-1", saved_path="/tmp/run-1/upload.mp4", run_dir="/tmp/run-1")

        self.assertEqual(self.media.visuals_calls, [dict(media_path="/tmp/run-1/upload.mp4")])
        self.assertIsNotNone(self.runs.runs["run-1"].thumbnail)

    async def test_caption_recovery_uses_only_yt_dlp_hints(self) -> None:
        self.media.download_error = MediaValidationError("HTTP Error 403: Forbidden")
        self.media.captions = CaptionTrack(
            text="hi",
            language="en",
            automatic=False,
            thumbnail_urls=("https://i.test/t.jpg",),
            width=1080,
            height=1920,
        )

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        self.assertEqual(
            self.media.visuals_calls,
            [dict(thumbnail_urls=("https://i.test/t.jpg",), width=1080, height=1920)],
        )
        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual(run.completeness, AnalysisCompleteness.CAPTIONS_ONLY)
        self.assertEqual(self.runs.visuals_written_while, [RunStatus.PROCESSING])

    async def test_audio_with_no_visuals_writes_nothing(self) -> None:
        self.media.visuals = MediaVisuals()
        await self.use_case.execute("run-1", source_url="https://x.test/a")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertEqual(self.runs.visuals_written_while, [])
        self.assertIsNone(run.thumbnail)

    async def test_a_raising_visuals_capture_does_not_fail_the_run(self) -> None:
        self.media.visuals_error = RuntimeError("ffmpeg exploded")
        await self.use_case.execute("run-1", source_url="https://x.test/v")

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.COMPLETE)
        self.assertIsNone(run.thumbnail)

    async def test_a_failed_visuals_write_does_not_fail_the_run(self) -> None:
        self.runs.set_visuals_error = RuntimeError("redis blip")
        await self.use_case.execute("run-1", source_url="https://x.test/v")

        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.COMPLETE)

    async def test_a_failed_analysis_cancels_an_unfinished_capture(self) -> None:
        cancelled = asyncio.Event()

        async def slow(**kwargs):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def failing_analysis(*args, **kwargs):
            await asyncio.sleep(0)  # let the capture task start
            raise MediaValidationError("bad file")

        self.media.describe_visuals = slow  # type: ignore[method-assign]
        self.analysis.analyze_with_retry = failing_analysis  # type: ignore[method-assign]

        await self.use_case.execute("run-1", source_url="https://x.test/v")

        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.runs.runs["run-1"].status, RunStatus.FAILED)
        self.assertEqual(self.media.cleaned_up, ["run-1"])


class FreeRunDownloadRefundTests(unittest.IsolatedAsyncioTestCase):
    """A link that cannot be fetched hands its free run back; anything that
    fails after the media is in hand (or at Gemini) does not."""

    URL = "https://www.instagram.com/p/private"
    PRIVATE = "This post isn't public."

    def setUp(self) -> None:
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.analysis = FakeAnalysisEngine(result=ANALYSIS)
        self.free_runs = FakeFreeRunAllowance()
        self.use_case = ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            analysis=self.analysis,
            free_runs=self.free_runs,
        )

    async def _intake(self, *, key: str | None = None, url: str | None = URL, file=None) -> str:
        """Admit a run through the real intake, so the hold is placed the
        way production places it."""
        create = CreateRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            queue=FakeJobQueue(),
            spend_cap=FakeSpendCap(),
            free_runs=self.free_runs,
            device_tokens=FakeDeviceTokens(),
            distributed=False,
        )
        run = await create.execute(
            principal=Principal(subject="client:owner", authenticated=False),
            accept_terms=True,
            file=file,
            url=url,
            gemini_api_key=key,
            device_token="good:dev-a",
            client_ip="1.1.1.1",
        )
        return run.run_id

    async def test_a_link_that_fails_to_download_refunds_the_free_run(self) -> None:
        run_id = await self._intake()
        self.assertEqual(self.free_runs.device_counts["dev-a"], 1)
        self.media.download_error = MediaValidationError(self.PRIVATE)

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.runs.runs[run_id].status, RunStatus.FAILED)
        self.assertEqual(self.free_runs.device_counts["dev-a"], 0)
        self.assertEqual(self.free_runs.ip_counts["1.1.1.1"], 0)
        self.assertEqual(len(self.free_runs.refunds), 1)

    async def test_an_unexpected_download_error_also_refunds(self) -> None:
        run_id = await self._intake()
        self.media.download_error = RuntimeError("yt-dlp blew up")

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.free_runs.device_counts["dev-a"], 0)

    async def test_a_failure_at_analyze_is_not_refunded(self) -> None:
        run_id = await self._intake()
        self.analysis.error = AnalysisUnavailableError("Gemini is busy.")

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.runs.runs[run_id].status, RunStatus.FAILED)
        self.assertEqual(self.free_runs.device_counts["dev-a"], 1)
        self.assertEqual(self.free_runs.refunds, [])
        # The hold is still cleared, so nothing can refund it later.
        self.assertEqual(self.free_runs.held, {})

    async def test_a_byok_run_that_fails_to_download_refunds_nothing(self) -> None:
        run_id = await self._intake(key="user-key")
        self.media.download_error = MediaValidationError(self.PRIVATE)

        await self.use_case.execute(run_id, source_url=self.URL, gemini_api_key="user-key")

        self.assertEqual(self.free_runs.consume_calls, 0)
        self.assertEqual(self.free_runs.refunds, [])

    async def test_never_refunds_the_same_run_twice(self) -> None:
        run_id = await self._intake()
        self.media.download_error = MediaValidationError(self.PRIVATE)

        # A retried job (arq max_tries) fails the download a second time.
        await self.use_case.execute(run_id, source_url=self.URL)
        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(len(self.free_runs.refunds), 1)
        self.assertEqual(self.free_runs.device_counts["dev-a"], 0)

    async def test_a_caption_rescue_completes_the_run_and_keeps_the_free_run(self) -> None:
        run_id = await self._intake()
        self.media.download_error = MediaValidationError("HTTP Error 403: Forbidden")
        self.media.captions = CAPTIONS

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.runs.runs[run_id].status, RunStatus.COMPLETE)
        self.assertEqual(self.free_runs.refunds, [])
        self.assertEqual(self.free_runs.held, {})

    async def test_captions_that_fail_at_gemini_are_not_refunded(self) -> None:
        run_id = await self._intake()
        self.media.download_error = MediaValidationError("HTTP Error 403: Forbidden")
        self.media.captions = CAPTIONS
        self.analysis.caption_error = AnalysisUnavailableError("Gemini is busy.")

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.runs.runs[run_id].status, RunStatus.FAILED)
        self.assertEqual(self.free_runs.refunds, [])

    async def test_too_long_after_downloading_is_refunded(self) -> None:
        run_id = await self._intake()
        self.media.enforce_duration_error = MediaValidationError("This video is too long.")

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.runs.runs[run_id].status, RunStatus.FAILED)
        self.assertEqual(self.runs.runs[run_id].error, "This video is too long.")
        self.assertEqual(len(self.free_runs.refunds), 1)
        self.assertEqual(self.free_runs.device_counts["dev-a"], 0)
        self.assertEqual(self.free_runs.ip_counts["1.1.1.1"], 0)
        self.assertEqual(self.free_runs.held, {})
        # Rejected before analysis: Gemini was never called.
        self.assertEqual(self.analysis.calls, [])

    async def test_too_long_after_downloading_never_refunds_twice(self) -> None:
        run_id = await self._intake()
        self.media.enforce_duration_error = MediaValidationError("This video is too long.")

        # A retried job (arq max_tries) hits the cap a second time.
        await self.use_case.execute(run_id, source_url=self.URL)
        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(len(self.free_runs.refunds), 1)
        self.assertEqual(self.free_runs.device_counts["dev-a"], 0)

    async def test_a_byok_run_that_is_too_long_refunds_nothing(self) -> None:
        run_id = await self._intake(key="user-key")
        self.media.enforce_duration_error = MediaValidationError("This video is too long.")

        await self.use_case.execute(run_id, source_url=self.URL, gemini_api_key="user-key")

        self.assertEqual(self.free_runs.consume_calls, 0)
        self.assertEqual(self.free_runs.refunds, [])

    async def test_an_upload_too_long_in_the_worker_is_not_refunded(self) -> None:
        # Uploads are checked for length at intake, which refunds there; the
        # worker's re-check of an S3 upload is not a second refund path.
        run_id = await self._intake(url=None, file=FakeUploadedFile())
        self.media.enforce_duration_error = MediaValidationError("This video is too long.")

        await self.use_case.execute(run_id, source_key=f"uploads/{run_id}.mp4")

        self.assertEqual(self.runs.runs[run_id].status, RunStatus.FAILED)
        self.assertEqual(self.free_runs.refunds, [])

    async def test_a_failure_at_normalize_after_downloading_is_not_refunded(self) -> None:
        run_id = await self._intake()
        self.media.normalize_error = MediaValidationError("Could not read this file.")

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.runs.runs[run_id].status, RunStatus.FAILED)
        self.assertEqual(self.free_runs.refunds, [])

    async def test_an_upload_that_fails_processing_is_not_refunded(self) -> None:
        run_id = await self._intake(url=None, file=FakeUploadedFile())
        self.analysis.error = MediaValidationError("bad file")

        await self.use_case.execute(
            run_id, saved_path=f"/tmp/{run_id}/upload.mp4", run_dir=f"/tmp/{run_id}"
        )

        self.assertEqual(self.runs.runs[run_id].status, RunStatus.FAILED)
        self.assertEqual(self.free_runs.refunds, [])

    async def test_a_failing_refund_does_not_change_the_run_outcome(self) -> None:
        run_id = await self._intake()
        self.media.download_error = MediaValidationError(self.PRIVATE)

        async def broken_release(run_id: str, *, refund: bool) -> bool:
            raise ConnectionError("redis down")

        self.free_runs.release = broken_release  # type: ignore[method-assign]

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.runs.runs[run_id].status, RunStatus.FAILED)
        self.assertEqual(self.runs.runs[run_id].error, self.PRIVATE)


class AccountFreeRunRefundTests(unittest.IsolatedAsyncioTestCase):
    """The account counterpart of FreeRunDownloadRefundTests: a signed-in
    account's link run rejected before analysis gets its account run back,
    through the same release in ProcessRunUseCase; others keep it."""

    URL = "https://www.instagram.com/p/private"

    def setUp(self) -> None:
        self.runs = FakeRunRepository()
        self.media = FakeMediaProcessor()
        self.analysis = FakeAnalysisEngine(result=ANALYSIS)
        self.free_runs = FakeFreeRunAllowance()
        self.accounts = FakeAccountFreeRunAllowance()
        self.use_case = ProcessRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            analysis=self.analysis,
            free_runs=self.free_runs,
            account_free_runs=self.accounts,
        )

    async def _intake(self) -> str:
        create = CreateRunUseCase(
            runs=self.runs,
            media=self.media,
            storage=FakeObjectStore(),
            queue=FakeJobQueue(),
            spend_cap=FakeSpendCap(),
            free_runs=self.free_runs,
            device_tokens=FakeDeviceTokens(),
            distributed=False,
            account_free_runs=self.accounts,
        )
        run = await create.execute(
            principal=Principal(subject="user:sub-1", authenticated=True, account_id="acct-1"),
            accept_terms=True,
            file=None,
            url=self.URL,
            gemini_api_key=None,
        )
        return run.run_id

    async def test_a_failed_download_hands_the_account_run_back(self) -> None:
        run_id = await self._intake()
        self.assertEqual(self.accounts.used("acct-1"), 1)
        self.media.download_error = MediaValidationError("This post is not public.")

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.accounts.used("acct-1"), 0)
        self.assertEqual(self.accounts.held, {})
        self.assertEqual(self.free_runs.refunds, [])

    async def test_the_duration_cap_after_download_hands_the_account_run_back(self) -> None:
        run_id = await self._intake()
        self.media.enforce_duration_error = MediaValidationError("too long")

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.accounts.used("acct-1"), 0)

    async def test_a_gemini_failure_keeps_the_account_run_spent(self) -> None:
        run_id = await self._intake()
        self.analysis.error = RuntimeError("gemini down")

        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(self.accounts.used("acct-1"), 1)
        self.assertEqual(self.accounts.held, {})

    async def test_a_retried_job_never_refunds_twice(self) -> None:
        run_id = await self._intake()
        self.media.download_error = MediaValidationError("This post is not public.")

        await self.use_case.execute(run_id, source_url=self.URL)
        await self.use_case.execute(run_id, source_url=self.URL)

        self.assertEqual(len(self.accounts.refunds), 1)
        self.assertEqual(self.accounts.used("acct-1"), 0)


if __name__ == "__main__":
    unittest.main()
