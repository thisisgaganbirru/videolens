"""The pre-flight video token estimate and GEMINI_VIDEO_TOKEN_BUDGET rule
(`token_estimate.py`): plain arithmetic, no Gemini client."""

import unittest

from app.infrastructure.ai.token_estimate import estimate_video_tokens, tokens_per_frame, within_budget


class EstimateTests(unittest.TestCase):
    def test_tokens_per_frame_follow_the_gemini_3_table(self) -> None:
        for resolution, expected in (("", 70), ("low", 70), ("medium", 70), ("high", 280)):
            with self.subTest(resolution=resolution):
                self.assertEqual(tokens_per_frame(resolution), expected)

    def test_unset_fps_is_gemini_default_of_one(self) -> None:
        # 180 s x (70 x 1 + 25): the doc table's 17.1k default row.
        self.assertEqual(estimate_video_tokens(180, 0, ""), 17_100)

    def test_the_doc_table_rows(self) -> None:
        self.assertEqual(estimate_video_tokens(180, 1, "high"), 54_900)
        self.assertEqual(estimate_video_tokens(180, 2, "high"), 105_300)
        self.assertEqual(estimate_video_tokens(600, 0, ""), 57_000)
        self.assertEqual(estimate_video_tokens(600, 1, "high"), 183_000)
        self.assertEqual(estimate_video_tokens(600, 2, "high"), 351_000)

    def test_half_fps_and_rounding_up(self) -> None:
        self.assertEqual(estimate_video_tokens(10, 0.5, "low"), 600)  # 10 x (35 + 25)
        self.assertEqual(estimate_video_tokens(0.1, 1, ""), 10)  # 9.5 rounds up

    def test_a_negative_length_counts_as_nothing(self) -> None:
        self.assertEqual(estimate_video_tokens(-5, 2, "high"), 0)


class BudgetTests(unittest.TestCase):
    def test_under_or_at_the_budget_keeps_the_settings(self) -> None:
        decision = within_budget(600, 2.0, "high", 351_000)
        self.assertEqual((decision.fps, decision.resolution, decision.downgraded), (2.0, "high", False))
        self.assertEqual(decision.estimate, 351_000)

    def test_over_the_budget_goes_back_to_defaults(self) -> None:
        decision = within_budget(600, 2.0, "high", 350_999)
        self.assertEqual((decision.fps, decision.resolution, decision.downgraded), (0.0, "", True))
        self.assertEqual(decision.estimate, 351_000)

    def test_a_budget_at_or_below_zero_is_off(self) -> None:
        for budget in (0, -1):
            with self.subTest(budget=budget):
                self.assertFalse(within_budget(10_000, 2.0, "high", budget).downgraded)

    def test_an_unknown_length_is_left_alone(self) -> None:
        decision = within_budget(None, 2.0, "high", 1)
        self.assertEqual((decision.fps, decision.resolution, decision.estimate), (2.0, "high", None))
        self.assertFalse(decision.downgraded)

    def test_default_settings_are_never_downgraded(self) -> None:
        decision = within_budget(100_000, 0.0, "", 1)
        self.assertFalse(decision.downgraded)
        self.assertEqual((decision.fps, decision.resolution), (0.0, ""))


if __name__ == "__main__":
    unittest.main()
