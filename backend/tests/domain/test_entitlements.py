import unittest
from decimal import Decimal

from app.domain.entitlements import (
    MediaResolution,
    Plan,
    billable_minutes,
    can_start_run,
    entitlement_for,
    estimate_cost_usd,
    media_resolution_for,
)


class EntitlementTableTests(unittest.TestCase):
    def test_every_plan_has_an_entitlement(self) -> None:
        for plan in Plan:
            self.assertIs(entitlement_for(plan).plan, plan)

    def test_accepts_plan_names_as_strings(self) -> None:
        self.assertIs(entitlement_for("pro").plan, Plan.PRO)

    def test_paid_plans_allow_longer_media_than_free(self) -> None:
        free = entitlement_for(Plan.FREE).max_duration_seconds
        for plan in (Plan.PRO, Plan.STUDIO, Plan.SCALE):
            self.assertGreater(entitlement_for(plan).max_duration_seconds, free)

    def test_free_is_hard_capped_and_paid_plans_have_overage(self) -> None:
        self.assertIsNone(entitlement_for(Plan.FREE).overage_usd_per_minute)
        for plan in (Plan.PRO, Plan.STUDIO, Plan.SCALE):
            self.assertIsNotNone(entitlement_for(plan).overage_usd_per_minute)

    def test_with_max_duration_overrides_only_when_positive(self) -> None:
        pro = entitlement_for(Plan.PRO)
        self.assertEqual(pro.with_max_duration(90).max_duration_seconds, 90)
        self.assertIs(pro.with_max_duration(None), pro)
        self.assertIs(pro.with_max_duration(0), pro)


class BillableMinutesTests(unittest.TestCase):
    def test_rounds_up_to_the_hundredth(self) -> None:
        self.assertEqual(billable_minutes(6), Decimal("0.10"))
        self.assertEqual(billable_minutes(61), Decimal("1.02"))

    def test_a_short_clip_is_never_free(self) -> None:
        self.assertGreater(billable_minutes(0.5), 0)

    def test_zero_or_negative_bills_nothing(self) -> None:
        self.assertEqual(billable_minutes(0), Decimal("0"))
        self.assertEqual(billable_minutes(-3), Decimal("0"))


class MediaResolutionTests(unittest.TestCase):
    def test_default_up_to_fifteen_minutes(self) -> None:
        self.assertIs(media_resolution_for(15 * 60), MediaResolution.DEFAULT)
        self.assertIs(media_resolution_for(None), MediaResolution.DEFAULT)

    def test_low_above_fifteen_minutes(self) -> None:
        self.assertIs(media_resolution_for(15 * 60 + 1), MediaResolution.LOW)

    def test_low_resolution_is_cheaper(self) -> None:
        self.assertLess(
            estimate_cost_usd(1200, MediaResolution.LOW),
            estimate_cost_usd(1200, MediaResolution.DEFAULT),
        )


class CanStartRunTests(unittest.TestCase):
    def test_free_blocks_once_minutes_are_used(self) -> None:
        free = entitlement_for(Plan.FREE)
        self.assertTrue(can_start_run(free, Decimal("29.99")))
        self.assertFalse(can_start_run(free, Decimal("30")))

    def test_paid_plan_with_overage_is_never_blocked(self) -> None:
        pro = entitlement_for(Plan.PRO)
        self.assertTrue(can_start_run(pro, Decimal("100000")))


if __name__ == "__main__":
    unittest.main()
