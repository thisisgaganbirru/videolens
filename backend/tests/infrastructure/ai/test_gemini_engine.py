import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import errors as genai_errors
from google.genai import types

from app.domain.entities import CaptionTrack, VideoAnalysis
from app.domain.errors import AnalysisUnavailableError
from app.infrastructure.ai.gemini_engine import GeminiEngine
from app.infrastructure.config import Settings


def _api_error(cls, code: int, message: str):
    return cls(code, {"error": {"code": code, "message": message, "status": "X"}})


def _busy() -> Exception:
    return _api_error(
        genai_errors.ServerError, 503, "This model is currently experiencing high demand."
    )


_RESULT = VideoAnalysis(
    title="t", summary="s", transcript="tr", screen_text="", markdown="# m"
)


class _FakeFiles:
    def __init__(self, upload_outcomes=None, states=None) -> None:
        self.upload_outcomes = list(upload_outcomes or [])
        self.states = list(states or [])
        self.upload_calls = 0
        self.get_calls = 0
        self.deleted: list[str] = []

    async def upload(self, file):
        self.upload_calls += 1
        if self.upload_outcomes:
            outcome = self.upload_outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        name = f"files/{self.upload_calls}"
        # A video or audio mime for the files GEMINI_VIDEO_FPS tells apart;
        # anything else (an image slide) keeps the generic one.
        mime_type = {".mp3": "audio/mpeg", ".mp4": "video/mp4"}.get(
            str(file)[-4:], "application/octet-stream"
        )
        return SimpleNamespace(name=name, uri=f"https://files.test/{name}", mime_type=mime_type)

    async def get(self, name):
        self.get_calls += 1
        state = self.states.pop(0) if self.states else types.FileState.ACTIVE
        if isinstance(state, Exception):
            raise state
        return SimpleNamespace(state=state)

    async def delete(self, name):
        self.deleted.append(name)


class _FakeModels:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.models_called: list[str] = []
        self.contents_seen: list[list] = []
        self.configs_seen: list = []

    async def generate_content(self, model, contents, config):
        self.models_called.append(model)
        self.contents_seen.append(contents)
        self.configs_seen.append(config)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(parsed=outcome, text=None)


class _FakeClient:
    def __init__(self, generate_outcomes, upload_outcomes=None, states=None) -> None:
        self.files = _FakeFiles(upload_outcomes, states)
        self.models = _FakeModels(generate_outcomes)
        self.closed: list[str] = []

        async def aclose() -> None:
            self.closed.append("async")

        self.aio = SimpleNamespace(files=self.files, models=self.models, aclose=aclose)

    def close(self) -> None:
        self.closed.append("sync")


def _engine(client: _FakeClient, rand: float = 1.0, **settings) -> tuple[GeminiEngine, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    # Explicit values throughout, so a developer's local .env cannot leak in.
    values = {
        "gemini_api_key": "server-key",
        "gemini_model": "primary-model",
        "gemini_fallback_model": "",
        "gemini_retry_attempts": 6,
        "gemini_retry_max_delay_seconds": 20.0,
        "gemini_slide_image_resolution": "high",
        "gemini_video_fps": 0.0,
        "gemini_media_resolution": "",
        **settings,
    }
    engine = GeminiEngine(
        Settings(**values),
        sleep=fake_sleep,
        rand=lambda: rand,
    )
    engine._client = client  # the shared-key client cache; no network
    return engine, sleeps


class TransientFailureClassificationTests(unittest.TestCase):
    """`_as_domain_error` is what stops a busy model being reported as an
    unknown failure. The 503 below is the real one seen in production:
    "This model is currently experiencing high demand."
    """

    def test_503_becomes_a_wait_and_retry_error(self) -> None:
        result = GeminiEngine._as_domain_error(
            _api_error(
                genai_errors.ServerError,
                503,
                "This model is currently experiencing high demand.",
            )
        )

        self.assertIsInstance(result, AnalysisUnavailableError)
        self.assertEqual(
            str(result), "Gemini is busy right now. This usually clears within a minute."
        )
        # The status code and class name are the operator's half.
        self.assertIn("503", result.log_detail)
        self.assertNotIn("503", str(result))

    def test_429_gets_its_own_wording(self) -> None:
        result = GeminiEngine._as_domain_error(
            _api_error(genai_errors.ClientError, 429, "Quota exceeded.")
        )

        self.assertIsInstance(result, AnalysisUnavailableError)
        self.assertEqual(str(result), "Too many requests right now. Try again in a moment.")

    def test_400_is_left_alone_for_the_generic_handler(self) -> None:
        """A malformed request will not succeed on a retry and is not the
        caller's doing, so it stays an unexpected error: masked in the UI,
        logged with a traceback."""
        original = _api_error(genai_errors.ClientError, 400, "Invalid argument.")

        self.assertIs(GeminiEngine._as_domain_error(original), original)

    def test_errors_without_a_status_are_left_alone(self) -> None:
        original = ValueError("something else entirely")

        self.assertIs(GeminiEngine._as_domain_error(original), original)


class AnalyzeRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_503_then_success_uploads_once(self) -> None:
        client = _FakeClient([_busy(), _RESULT])
        engine, sleeps = _engine(client)

        result = await engine.analyze_with_retry("clip.mp4")

        self.assertIs(result, _RESULT)
        self.assertEqual(client.files.upload_calls, 1)
        self.assertEqual(client.models.models_called, ["primary-model", "primary-model"])
        self.assertEqual(sleeps, [2.0])
        await engine.drain()  # the deletes run in the background
        self.assertEqual(client.files.deleted, ["files/1"])

    async def test_non_transient_error_raises_immediately(self) -> None:
        bad_request = _api_error(genai_errors.ClientError, 400, "Invalid argument.")
        client = _FakeClient([bad_request, _RESULT])
        engine, sleeps = _engine(client)

        with self.assertRaises(genai_errors.ClientError) as caught:
            await engine.analyze_with_retry("clip.mp4")

        self.assertIs(caught.exception, bad_request)
        self.assertEqual(len(client.models.models_called), 1)
        self.assertEqual(client.files.upload_calls, 1)
        self.assertEqual(sleeps, [])
        await engine.drain()  # the deletes run in the background
        self.assertEqual(client.files.deleted, ["files/1"])

    async def test_exhausted_retries_raise_analysis_unavailable(self) -> None:
        client = _FakeClient([_busy() for _ in range(6)])
        engine, sleeps = _engine(client)

        with self.assertRaises(AnalysisUnavailableError) as caught:
            await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(
            str(caught.exception),
            "Gemini is busy right now. This usually clears within a minute.",
        )
        self.assertEqual(len(client.models.models_called), 6)
        self.assertEqual(client.files.upload_calls, 1)
        # rand=1.0 pins each sleep to its ceiling: the ~50s worst case.
        self.assertEqual(sleeps, [2.0, 4.0, 8.0, 16.0, 20.0])
        await engine.drain()  # the deletes run in the background
        self.assertEqual(client.files.deleted, ["files/1"])

    def test_default_retry_settings(self) -> None:
        fields = Settings.model_fields
        self.assertEqual(fields["gemini_retry_attempts"].default, 6)
        self.assertEqual(fields["gemini_retry_max_delay_seconds"].default, 20.0)
        self.assertEqual(fields["gemini_fallback_model"].default, "")
        self.assertEqual(fields["gemini_slide_image_resolution"].default, "high")

    async def test_exhausted_429_keeps_its_own_wording(self) -> None:
        quota = _api_error(genai_errors.ClientError, 429, "Quota exceeded.")
        client = _FakeClient([quota, quota])
        engine, _ = _engine(client, gemini_retry_attempts=2)

        with self.assertRaises(AnalysisUnavailableError) as caught:
            await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(
            str(caught.exception), "Too many requests right now. Try again in a moment."
        )

    async def test_backoff_doubles_and_is_capped(self) -> None:
        client = _FakeClient([_busy() for _ in range(6)] + [_RESULT])
        # rand=1.0 pins full jitter to its ceiling so the schedule is visible.
        engine, sleeps = _engine(
            client, gemini_retry_attempts=7, gemini_retry_max_delay_seconds=10.0
        )

        await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(sleeps, [2.0, 4.0, 8.0, 10.0, 10.0, 10.0])

    async def test_jitter_scales_the_delay(self) -> None:
        client = _FakeClient([_busy(), _busy(), _RESULT])
        engine, sleeps = _engine(client, rand=0.25)

        await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(sleeps, [0.5, 1.0])

    async def test_fallback_model_serves_after_primary_exhausts(self) -> None:
        client = _FakeClient([_busy(), _busy(), _busy(), _RESULT])
        engine, _ = _engine(
            client, gemini_retry_attempts=3, gemini_fallback_model="fallback-model"
        )

        result = await engine.analyze_with_retry("clip.mp4")

        self.assertIs(result, _RESULT)
        self.assertEqual(
            client.models.models_called,
            ["primary-model", "primary-model", "primary-model", "fallback-model"],
        )
        # Same uploaded file handed to the fallback - no second upload.
        self.assertEqual(client.files.upload_calls, 1)
        self.assertIs(client.models.contents_seen[-1][0], client.models.contents_seen[0][0])

    async def test_fallback_gets_a_short_cycle_then_maps_the_error(self) -> None:
        client = _FakeClient([_busy() for _ in range(4)])
        engine, _ = _engine(
            client, gemini_retry_attempts=2, gemini_fallback_model="fallback-model"
        )

        with self.assertRaises(AnalysisUnavailableError):
            await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(
            client.models.models_called,
            ["primary-model", "primary-model", "fallback-model", "fallback-model"],
        )

    async def test_blank_fallback_means_primary_only(self) -> None:
        client = _FakeClient([_busy(), _busy()])
        engine, _ = _engine(client, gemini_retry_attempts=2, gemini_fallback_model="  ")

        with self.assertRaises(AnalysisUnavailableError):
            await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(client.models.models_called, ["primary-model", "primary-model"])

    async def test_fallback_equal_to_primary_is_ignored(self) -> None:
        client = _FakeClient([_busy(), _busy()])
        engine, _ = _engine(
            client, gemini_retry_attempts=2, gemini_fallback_model="primary-model"
        )

        with self.assertRaises(AnalysisUnavailableError):
            await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(len(client.models.models_called), 2)

    async def test_non_transient_error_does_not_trigger_fallback(self) -> None:
        bad_request = _api_error(genai_errors.ClientError, 400, "Invalid argument.")
        client = _FakeClient([bad_request])
        engine, _ = _engine(client, gemini_fallback_model="fallback-model")

        with self.assertRaises(genai_errors.ClientError):
            await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(client.models.models_called, ["primary-model"])

    async def test_transient_upload_failure_is_retried(self) -> None:
        client = _FakeClient([_RESULT], upload_outcomes=[_busy()])
        engine, sleeps = _engine(client)

        result = await engine.analyze_with_retry("clip.mp4")

        self.assertIs(result, _RESULT)
        self.assertEqual(client.files.upload_calls, 2)
        self.assertEqual(sleeps, [2.0])

    async def test_failed_file_processing_reuploads_once(self) -> None:
        client = _FakeClient([_RESULT], states=[types.FileState.FAILED])
        engine, _ = _engine(client)

        result = await engine.analyze_with_retry("clip.mp4")

        self.assertIs(result, _RESULT)
        self.assertEqual(client.files.upload_calls, 2)
        await engine.drain()  # the deletes run in the background
        self.assertEqual(client.files.deleted, ["files/1", "files/2"])

    async def test_transient_poll_error_then_active_succeeds(self) -> None:
        client = _FakeClient(
            [_RESULT], states=[_busy(), types.FileState.PROCESSING, types.FileState.ACTIVE]
        )
        engine, sleeps = _engine(client)

        result = await engine.analyze_with_retry("clip.mp4")

        self.assertIs(result, _RESULT)
        self.assertEqual(client.files.get_calls, 3)
        self.assertEqual(client.files.upload_calls, 1)
        # One backoff sleep for the 503, then one 2s poll interval.
        self.assertEqual(sleeps, [2.0, 2.0])

    async def test_non_transient_poll_error_raises_without_retry(self) -> None:
        not_found = _api_error(genai_errors.ClientError, 404, "File not found.")
        client = _FakeClient([_RESULT], states=[not_found])
        engine, sleeps = _engine(client)

        with self.assertRaises(genai_errors.ClientError) as caught:
            await engine.analyze_with_retry("clip.mp4")

        self.assertIs(caught.exception, not_found)
        self.assertEqual(client.files.get_calls, 1)
        self.assertEqual(client.files.upload_calls, 1)
        self.assertEqual(client.models.models_called, [])
        self.assertEqual(sleeps, [])
        await engine.drain()  # the deletes run in the background
        self.assertEqual(client.files.deleted, ["files/1"])

    async def test_exhausted_transient_poll_errors_map_to_unavailable(self) -> None:
        client = _FakeClient([_RESULT], states=[_busy(), _busy(), _busy()])
        engine, _ = _engine(client, gemini_retry_attempts=3)

        with self.assertRaises(AnalysisUnavailableError):
            await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(client.files.get_calls, 3)
        # A busy poll is not a processing failure: no re-upload.
        self.assertEqual(client.files.upload_calls, 1)
        self.assertEqual(client.models.models_called, [])
        await engine.drain()  # the deletes run in the background
        self.assertEqual(client.files.deleted, ["files/1"])

    async def test_retry_logs_status_and_model_but_never_the_key(self) -> None:
        client = _FakeClient([_busy(), _RESULT])
        engine, _ = _engine(client)

        with self.assertLogs("app.infrastructure.ai.gemini_engine", "WARNING") as logs:
            await engine.analyze_with_retry("clip.mp4", api_key=None)

        output = "\n".join(logs.output)
        self.assertIn("503", output)
        self.assertIn("primary-model", output)
        self.assertIn("1/6", output)
        self.assertNotIn("server-key", output)

    async def test_stage_callbacks_still_fire(self) -> None:
        client = _FakeClient([_busy(), _RESULT])
        engine, _ = _engine(client)
        stages: list[str] = []

        async def on_stage(stage: str) -> None:
            stages.append(stage)

        await engine.analyze_with_retry("clip.mp4", on_stage=on_stage)

        self.assertEqual(stages, ["uploading_to_gemini", "analyzing"])


class AnalyzeCaptionsRetryTests(unittest.IsolatedAsyncioTestCase):
    _CAPTIONS = CaptionTrack(text="hello world", language="en", automatic=True)

    async def test_captions_retry_transient_errors(self) -> None:
        client = _FakeClient([_busy(), _RESULT])
        engine, sleeps = _engine(client)

        result = await engine.analyze_captions(self._CAPTIONS)

        self.assertIs(result, _RESULT)
        self.assertEqual(client.models.models_called, ["primary-model", "primary-model"])
        self.assertEqual(client.files.upload_calls, 0)
        self.assertEqual(sleeps, [2.0])

    async def test_captions_use_the_fallback(self) -> None:
        client = _FakeClient([_busy(), _RESULT])
        engine, _ = _engine(
            client, gemini_retry_attempts=1, gemini_fallback_model="fallback-model"
        )

        result = await engine.analyze_captions(self._CAPTIONS)

        self.assertIs(result, _RESULT)
        self.assertEqual(client.models.models_called, ["primary-model", "fallback-model"])

    async def test_captions_exhausted_raise_analysis_unavailable(self) -> None:
        client = _FakeClient([_busy(), _busy()])
        engine, _ = _engine(client, gemini_retry_attempts=2)

        with self.assertRaises(AnalysisUnavailableError):
            await engine.analyze_captions(self._CAPTIONS)


class OwnKeyClientLifetimeTests(unittest.IsolatedAsyncioTestCase):
    """A per-BYOK client is closed when its run is done; the shared
    server-key client is cached and left open."""

    _CAPTIONS = CaptionTrack(text="hello world", language="en", automatic=True)

    async def test_an_own_key_client_is_closed_after_the_run_whatever_happens(self) -> None:
        cases = {
            "success": lambda engine: engine.analyze_with_retry("clip.mp4", api_key="own-key"),
            "upload fails": lambda engine: engine.analyze_with_retry("clip.mp4", api_key="own-key"),
            "captions": lambda engine: engine.analyze_captions(self._CAPTIONS, api_key="own-key"),
        }
        for name, call in cases.items():
            with self.subTest(name):
                own = _FakeClient(
                    [_RESULT], upload_outcomes=[ValueError("bad file")] if name == "upload fails" else None
                )
                engine, _ = _engine(_FakeClient([_RESULT]))
                with patch("app.infrastructure.ai.gemini_engine.genai.Client", return_value=own):
                    try:
                        await call(engine)
                    except ValueError:
                        pass
                await engine.drain()  # the release follows the background deletes
                self.assertEqual(own.closed, ["async", "sync"])

    async def test_the_shared_client_stays_open(self) -> None:
        shared = _FakeClient([_RESULT, _RESULT])
        engine, _ = _engine(shared)
        await engine.analyze_with_retry("clip.mp4", api_key=None)
        await engine.analyze_captions(self._CAPTIONS)
        self.assertEqual(shared.closed, [])

    async def test_a_close_failure_never_fails_the_run(self) -> None:
        own = _FakeClient([_RESULT])

        def broken() -> None:
            raise RuntimeError("already closed")

        own.close = broken
        engine, _ = _engine(_FakeClient([]))
        with patch("app.infrastructure.ai.gemini_engine.genai.Client", return_value=own):
            self.assertIs(await engine.analyze_captions(self._CAPTIONS, api_key="own-key"), _RESULT)


class VideoSamplingTests(unittest.IsolatedAsyncioTestCase):
    """GEMINI_VIDEO_FPS and GEMINI_MEDIA_RESOLUTION. Unset, the request is
    exactly what it was before they existed: the bare uploaded file and no
    media_resolution on the config."""

    async def test_unset_sends_the_bare_file_and_no_resolution(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client)

        await engine.analyze_with_retry("clip.mp4")

        media = client.models.contents_seen[0][0]
        self.assertIsInstance(media, SimpleNamespace)  # the upload, unwrapped
        self.assertIsNone(client.models.configs_seen[0].media_resolution)

    async def test_fps_wraps_a_video_with_video_metadata(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, gemini_video_fps=2.0)

        await engine.analyze_with_retry("clip.mp4")

        media = client.models.contents_seen[0][0]
        self.assertIsInstance(media, types.Part)
        self.assertEqual(media.file_data.file_uri, "https://files.test/files/1")
        self.assertEqual(media.file_data.mime_type, "video/mp4")
        self.assertEqual(media.video_metadata.fps, 2.0)

    async def test_fps_leaves_audio_alone(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, gemini_video_fps=2.0)

        await engine.analyze_with_retry("normalized.mp3")

        self.assertIsInstance(client.models.contents_seen[0][0], SimpleNamespace)

    async def test_resolution_is_set_on_the_request(self) -> None:
        for value, expected in (
            ("low", types.MediaResolution.MEDIA_RESOLUTION_LOW),
            ("medium", types.MediaResolution.MEDIA_RESOLUTION_MEDIUM),
            ("high", types.MediaResolution.MEDIA_RESOLUTION_HIGH),
        ):
            with self.subTest(value=value):
                client = _FakeClient([_RESULT])
                engine, _ = _engine(client, gemini_media_resolution=value)
                await engine.analyze_with_retry("clip.mp4")
                self.assertEqual(client.models.configs_seen[0].media_resolution, expected)

    async def test_fallback_gets_the_same_media_part_and_config(self) -> None:
        client = _FakeClient([_busy(), _RESULT])
        engine, _ = _engine(
            client,
            gemini_retry_attempts=1,
            gemini_fallback_model="fallback-model",
            gemini_video_fps=2.0,
            gemini_media_resolution="high",
        )

        await engine.analyze_with_retry("clip.mp4")

        self.assertEqual(client.models.models_called, ["primary-model", "fallback-model"])
        self.assertIs(client.models.contents_seen[1][0], client.models.contents_seen[0][0])
        self.assertIs(client.models.configs_seen[1], client.models.configs_seen[0])

    async def test_captions_never_carry_a_resolution(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client, gemini_media_resolution="high", gemini_video_fps=2.0)

        await engine.analyze_captions(CaptionTrack(language="en", automatic=False, text="hi"))

        self.assertIsNone(client.models.configs_seen[0].media_resolution)
        self.assertEqual(client.models.contents_seen[0][0], "Caption track language: en (publisher-provided)")


if __name__ == "__main__":
    unittest.main()
