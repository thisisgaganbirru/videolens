"""BillingProbe (the `billing` capability row) and the billing settings:
`billing_configured`, the Checkout return origin, and the distributed
fail-fast without a database."""

import unittest

from app.domain.entities import BillingPrices, CapabilityState, Price
from app.infrastructure.config import Settings
from app.infrastructure.health.probes import BillingProbe

STRIPE = dict(
    stripe_secret_key="sk_test_1",
    stripe_webhook_secret="whsec_1",
    stripe_price_monthly="price_m",
    stripe_price_extra_run="price_x",
)


class _Gateway:
    def __init__(self, enabled=True, prices=None, test_mode=True) -> None:
        self.enabled = enabled
        self.test_mode = test_mode
        self._prices = prices if prices is not None else BillingPrices(month=Price(amount=1200, currency="usd"))

    async def prices(self):
        return self._prices


class _Accounts:
    def __init__(self, enabled=True) -> None:
        self.enabled = enabled


class BillingProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured_is_disabled_and_not_probed(self) -> None:
        for gateway, accounts in ((_Gateway(enabled=False), _Accounts()), (_Gateway(), _Accounts(enabled=False))):
            row = await BillingProbe(gateway, accounts).check()
            self.assertEqual((row.name, row.state, row.probed), ("billing", CapabilityState.DISABLED, False))

    async def test_prices_read_is_ok(self) -> None:
        row = await BillingProbe(_Gateway(), _Accounts()).check()
        self.assertEqual((row.state, row.probed), (CapabilityState.OK, True))
        self.assertIn("test mode", row.log_detail)

    async def test_unreadable_monthly_price_is_degraded(self) -> None:
        row = await BillingProbe(_Gateway(prices=BillingPrices()), _Accounts()).check()
        self.assertEqual(row.state, CapabilityState.DEGRADED)


class BillingSettingsTests(unittest.TestCase):
    def test_configured_needs_every_required_value(self) -> None:
        self.assertTrue(Settings(_env_file=None, **STRIPE).billing_configured)
        self.assertFalse(Settings(_env_file=None).billing_configured)
        for key in STRIPE:
            self.assertFalse(Settings(_env_file=None, **{**STRIPE, key: " "}).billing_configured, key)

    def test_return_base(self) -> None:
        self.assertEqual(
            Settings(_env_file=None, billing_return_origin="https://app.test/").billing_return_base, "https://app.test"
        )
        self.assertEqual(
            Settings(_env_file=None, allowed_origins="*, https://a.test,https://b.test").billing_return_base,
            "https://a.test",
        )

    def test_distributed_billing_needs_a_database(self) -> None:
        distributed = dict(redis_url="redis://r:6379/0", **STRIPE)
        self.assertIsNotNone(Settings(_env_file=None, **distributed).distributed_billing_error())
        self.assertIsNone(
            Settings(_env_file=None, database_url="postgresql+asyncpg://x/y", **distributed).distributed_billing_error()
        )
        # Billing off, or local: nothing to refuse.
        self.assertIsNone(Settings(_env_file=None, redis_url="redis://r:6379/0").distributed_billing_error())
        self.assertIsNone(Settings(_env_file=None, **STRIPE).distributed_billing_error())

    def test_paid_defaults(self) -> None:
        settings = Settings(_env_file=None)
        self.assertEqual((settings.paid_runs_per_day, settings.paid_extra_runs_monthly_cap), (30, 200))
        self.assertEqual(settings.stripe_meter_event_name, "videolens_extra_run")


if __name__ == "__main__":
    unittest.main()
