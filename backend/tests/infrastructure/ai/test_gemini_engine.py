import unittest
from types import SimpleNamespace

from google.genai import errors as genai_errors
from google.genai import types

from app.domain.entities import CaptionTrack, TokenUsage, VideoAnalysis
from app.domain.entitlements import MediaResolution
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
        return SimpleNamespace(name=f"files/{self.upload_calls}")

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
        return SimpleNamespace(
            parsed=outcome,
            text=None,
            usage_metadata=SimpleNamespace(prompt_token_count=1200, candidates_token_count=300),
        )


class _FakeClient:
    def __init__(self, generate_outcomes, upload_outcomes=None, states=None) -> None:
        self.files = _FakeFiles(upload_outcomes, states)
        self.models = _FakeModels(generate_outcomes)
        self.aio = SimpleNamespace(files=self.files, models=self.models)


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
        self.assertEqual(client.files.deleted, ["files/1"])

    def test_default_retry_settings(self) -> None:
        fields = Settings.model_fields
        self.assertEqual(fields["gemini_retry_attempts"].default, 6)
        self.assertEqual(fields["gemini_retry_max_delay_seconds"].default, 20.0)
        self.assertEqual(fields["gemini_fallback_model"].default, "")

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

    async def test_fallback_keeps_resolution_and_reports_usage_once(self) -> None:
        """Paid-tier parameters survive the retry/fallback path: every attempt
        (primary and fallback) carries the plan's media resolution, and usage
        is reported exactly once, from the response that succeeded."""
        client = _FakeClient([_busy(), _busy(), _RESULT])
        engine, _ = _engine(
            client, gemini_retry_attempts=2, gemini_fallback_model="fallback-model"
        )
        reported: list[TokenUsage] = []

        async def on_usage(usage: TokenUsage) -> None:
            reported.append(usage)

        result = await engine.analyze_with_retry(
            "clip.mp4", resolution=MediaResolution.LOW, on_usage=on_usage
        )

        self.assertIs(result, _RESULT)
        self.assertEqual(
            client.models.models_called, ["primary-model", "primary-model", "fallback-model"]
        )
        self.assertEqual(
            [c.media_resolution for c in client.models.configs_seen],
            [types.MediaResolution.MEDIA_RESOLUTION_LOW] * 3,
        )
        self.assertEqual(reported, [TokenUsage(input_tokens=1200, output_tokens=300)])

    async def test_default_resolution_leaves_the_sdk_default(self) -> None:
        client = _FakeClient([_RESULT])
        engine, _ = _engine(client)

        await engine.analyze_with_retry("clip.mp4")

        self.assertIsNone(client.models.configs_seen[0].media_resolution)

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


if __name__ == "__main__":
    unittest.main()
