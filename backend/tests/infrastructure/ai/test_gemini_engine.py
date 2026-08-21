import unittest

from google.genai import errors as genai_errors

from app.domain.errors import AnalysisUnavailableError
from app.infrastructure.ai.gemini_engine import GeminiEngine


def _api_error(cls, code: int, message: str):
    return cls(code, {"error": {"code": code, "message": message, "status": "X"}})


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


if __name__ == "__main__":
    unittest.main()
