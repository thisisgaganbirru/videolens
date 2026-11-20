"""What a person sees when the Gemini key they brought is wrong.

Gemini refuses an invalid key with a 400 (`API_KEY_INVALID`). The engine
retries and rewords only 429/5xx, so the 400 reaches `ProcessRunUseCase`
as an unexpected error and the run stores the generic failure message.
This pins today's behaviour: the run fails, the key never appears in the
stored message, and nothing falls back to the shared key. No doc promises
a key-specific message (docs/backend/byok.md)."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import errors as genai_errors

from app.application.process_run import ProcessRunUseCase
from app.domain.entities import RunStatus
from app.infrastructure.ai.gemini_engine import GeminiEngine
from app.infrastructure.config import Settings

from .fakes import FakeFreeRunAllowance, FakeMediaProcessor, FakeObjectStore, FakeRunRepository, FakeSpendCap

BAD_KEY = "AIzaSy-not-a-real-key-0123456789"
GENERIC_FAILURE = "The analysis didn't finish. Please try again."


class _RefusingClient:
    """A genai client whose every call is refused as Gemini refuses a bad key."""

    def __init__(self) -> None:
        self.uploads = 0

        async def upload(file):
            self.uploads += 1
            raise genai_errors.ClientError(
                400,
                {
                    "error": {
                        "code": 400,
                        "message": "API key not valid. Please pass a valid API key.",
                        "status": "INVALID_ARGUMENT",
                        "details": [{"reason": "API_KEY_INVALID"}],
                    }
                },
            )

        async def aclose() -> None:
            pass

        self.aio = SimpleNamespace(files=SimpleNamespace(upload=upload), aclose=aclose)

    def close(self) -> None:
        pass


class InvalidOwnKeyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.spend_cap = FakeSpendCap()
        self.engine = GeminiEngine(
            Settings(_env_file=None, gemini_api_key="server-key", gemini_retry_attempts=3),
            sleep=self._no_sleep,
        )
        self.use_case = ProcessRunUseCase(
            runs=self.runs,
            media=FakeMediaProcessor(),
            storage=FakeObjectStore(),
            analysis=self.engine,
            free_runs=FakeFreeRunAllowance(),
            spend_cap=self.spend_cap,
        )
        await self.runs.create("run-1", "client:owner", admitted_byok=True)

    @staticmethod
    async def _no_sleep(seconds: float) -> None:
        pass

    async def test_an_invalid_own_key_fails_the_run_with_the_generic_message(self) -> None:
        own = _RefusingClient()
        with patch("app.infrastructure.ai.gemini_engine.genai.Client", return_value=own) as build, self.assertLogs(
            "videolens", level="ERROR"
        ):
            await self.use_case.execute("run-1", source_url="https://x.test/v.mp4", gemini_api_key=BAD_KEY)

        run = self.runs.runs["run-1"]
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error, GENERIC_FAILURE)
        self.assertNotIn(BAD_KEY, run.error)
        # A 400 is not retried, and only the caller's key was ever used.
        self.assertEqual(own.uploads, 1)
        self.assertEqual([call.kwargs["api_key"] for call in build.call_args_list], [BAD_KEY])
        self.assertIsNone(self.engine._client)
        # An own-key run never touched the shared cap.
        self.assertEqual(self.spend_cap.consume_calls, 0)


if __name__ == "__main__":
    unittest.main()
