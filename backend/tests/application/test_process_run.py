import os
import unittest

from app.application.process_run import ProcessRunUseCase
from app.domain.entities import (
    AnalysisCompleteness,
    CaptionTrack,
    RunStatus,
    SourceMetadata,
    VideoAnalysis,
)
from app.domain.errors import GeminiConfigurationError, MediaValidationError

from .fakes import (
    FakeAnalysisEngine,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
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
        return ProcessRunUseCase(runs=self.runs, media=self.media, storage=self.storage, analysis=self.analysis)

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

    async def test_unexpected_exception_is_masked_with_a_generic_error_message(self) -> None:
        use_case = self._make_use_case(analysis=FakeAnalysisEngine(error=RuntimeError("stack trace with secrets")))
        await self.runs.create("run-3", "client:owner")
        await use_case.execute("run-3", saved_path="/tmp/run-3/upload.mp4", run_dir="/tmp/run-3")

        run = self.runs.runs["run-3"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, "Media analysis failed. Please try again.")
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


if __name__ == "__main__":
    unittest.main()
