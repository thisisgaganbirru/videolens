import os
import unittest

from app.application.process_run import ProcessRunUseCase
from app.domain.entities import RunStatus, SourceMetadata, VideoAnalysis
from app.domain.errors import (
    AnalysisUnavailableError,
    GeminiConfigurationError,
    MediaValidationError,
)

from .fakes import (
    FakeAnalysisEngine,
    FakeMediaProcessor,
    FakeObjectStore,
    FakeRunRepository,
    RaisingObjectStore,
)

ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="Tx", screen_text="", markdown="# T")


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


if __name__ == "__main__":
    unittest.main()
