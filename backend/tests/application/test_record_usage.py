import unittest
from decimal import Decimal

from app.application.record_usage import RecordUsageUseCase
from app.domain.entities import TokenUsage
from app.domain.entitlements import MediaResolution, estimate_cost_usd

from .fakes import FakeAccountDirectory, FakeBillingGateway, FakeUsageMeter, make_workspace


class BrokenMeterGateway(FakeBillingGateway):
    async def report_usage(self, *, customer_id: str, minutes: Decimal, run_id: str) -> str | None:
        raise RuntimeError("Stripe is down")


class RecordUsageTests(unittest.IsolatedAsyncioTestCase):
    def _make(self, *, billing=None, customer: str | None = None) -> RecordUsageUseCase:
        self.usage = FakeUsageMeter()
        self.accounts = FakeAccountDirectory()
        self.accounts.add_workspace(make_workspace(stripe_customer_id=customer))
        self.billing = billing or FakeBillingGateway()
        return RecordUsageUseCase(usage=self.usage, accounts=self.accounts, billing=self.billing)

    async def _run(self, use_case: RecordUsageUseCase, **overrides):
        params = dict(
            run_id="run-1",
            workspace_id="ws-pro",
            duration_seconds=42.0,
            resolution=MediaResolution.DEFAULT,
            tokens=TokenUsage(input_tokens=1200, output_tokens=300),
        )
        params.update(overrides)
        return await use_case.execute(**params)

    async def test_records_minutes_rounded_up_with_tokens_and_cost(self) -> None:
        use_case = self._make()

        event = await self._run(use_case)

        self.assertEqual(self.usage.events, [event])
        self.assertEqual(event.minutes_billed, Decimal("0.70"))
        self.assertEqual((event.input_tokens, event.output_tokens), (1200, 300))
        self.assertEqual(event.cost_estimate_usd, estimate_cost_usd(42.0, MediaResolution.DEFAULT))
        self.assertIsNone(event.meter_event_id)
        self.assertEqual(self.billing.reported, [])

    async def test_missing_token_counts_record_as_zero(self) -> None:
        use_case = self._make()
        event = await self._run(use_case, tokens=None)
        self.assertEqual((event.input_tokens, event.output_tokens), (0, 0))

    async def test_reports_to_the_billing_meter_when_the_workspace_has_a_customer(self) -> None:
        use_case = self._make(customer="cus_1")

        event = await self._run(use_case, duration_seconds=1000.0, resolution=MediaResolution.LOW)

        self.assertEqual(event.meter_event_id, "meter-run-1")
        self.assertEqual(
            self.billing.reported, [dict(customer_id="cus_1", minutes=Decimal("16.67"), run_id="run-1")]
        )

    async def test_a_meter_failure_still_records_locally(self) -> None:
        use_case = self._make(billing=BrokenMeterGateway(), customer="cus_1")

        with self.assertLogs("videolens", level="ERROR"):
            event = await self._run(use_case)

        self.assertEqual(self.usage.events, [event])
        self.assertIsNone(event.meter_event_id)

    async def test_disabled_billing_never_reports(self) -> None:
        use_case = self._make(billing=FakeBillingGateway(enabled=False), customer="cus_1")
        await self._run(use_case)
        self.assertEqual(self.billing.reported, [])


if __name__ == "__main__":
    unittest.main()
