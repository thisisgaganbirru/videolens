"""StripeBillingGateway against a mocked StripeClient (never the network):
what is sent to Stripe, how its objects are reduced to domain records, and
real webhook signature verification with a locally computed signature."""

import hashlib
import hmac
import json
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

import stripe

from app.domain.entities import ExtraRunCharge
from app.domain.errors import BillingNotConfiguredError, BillingProviderError, WebhookSignatureError
from app.infrastructure.billing.stripe_gateway import StripeBillingGateway
from app.infrastructure.config import Settings

SECRET = "whsec_test_secret"


def _settings(**overrides) -> Settings:
    values = dict(
        _env_file=None,
        gemini_api_key="k",
        stripe_secret_key="sk_test_123",
        stripe_webhook_secret=SECRET,
        stripe_price_monthly="price_month",
        stripe_price_yearly="price_year",
        stripe_price_extra_run="price_extra",
        allowed_origins="https://videolens.test",
    )
    values.update(overrides)
    return Settings(**values)


def _signed(payload: bytes, secret: str = SECRET) -> str:
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


class StripeGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = mock.MagicMock()
        self.gateway = StripeBillingGateway(_settings(), client=self.client)

    def test_enabled_needs_every_required_setting(self) -> None:
        self.assertTrue(self.gateway.enabled)
        self.assertTrue(self.gateway.test_mode)
        for blank in ("stripe_secret_key", "stripe_webhook_secret", "stripe_price_monthly", "stripe_price_extra_run"):
            self.assertFalse(StripeBillingGateway(_settings(**{blank: ""})).enabled, blank)
        # Yearly is optional.
        gateway = StripeBillingGateway(_settings(stripe_price_yearly=""))
        self.assertTrue(gateway.enabled)
        self.assertFalse(gateway.yearly_available)

    async def test_disabled_refuses_every_call(self) -> None:
        gateway = StripeBillingGateway(_settings(stripe_secret_key=""), client=self.client)
        with self.assertRaises(BillingNotConfiguredError):
            await gateway.create_customer("acct-1", None)
        with self.assertRaises(BillingNotConfiguredError):
            gateway.parse_webhook(b"{}", "sig")
        self.assertIsNone((await gateway.prices()).month)
        self.client.assert_not_called()

    async def test_checkout_session(self) -> None:
        self.client.v1.checkout.sessions.create.return_value = {"url": "https://checkout.stripe.com/c/1"}
        url = await self.gateway.create_checkout_session(customer_id="cus_1", account_id="acct-1", interval="year")
        self.assertEqual(url, "https://checkout.stripe.com/c/1")
        params = self.client.v1.checkout.sessions.create.call_args.kwargs["params"]
        self.assertEqual(params["mode"], "subscription")
        self.assertEqual(params["client_reference_id"], "acct-1")
        # The metered price takes no quantity; mixed intervals need flexible.
        self.assertEqual(params["line_items"], [{"price": "price_year", "quantity": 1}, {"price": "price_extra"}])
        self.assertEqual(params["subscription_data"]["billing_mode"], {"type": "flexible"})
        self.assertEqual(params["subscription_data"]["metadata"], {"account_id": "acct-1"})
        self.assertEqual(params["success_url"], "https://videolens.test/app?view=account&billing=success")
        self.assertEqual(params["cancel_url"], "https://videolens.test/app?view=account&billing=cancel")

    async def test_a_yearly_metered_price_replaces_the_monthly_one_on_yearly_plans(self) -> None:
        gateway = StripeBillingGateway(_settings(stripe_price_extra_run_yearly="price_extra_y"), client=self.client)
        self.client.v1.checkout.sessions.create.return_value = {"url": "u"}
        await gateway.create_checkout_session(customer_id="cus_1", account_id="acct-1", interval="year")
        items = self.client.v1.checkout.sessions.create.call_args.kwargs["params"]["line_items"]
        self.assertEqual(items[1], {"price": "price_extra_y"})
        await gateway.create_checkout_session(customer_id="cus_1", account_id="acct-1", interval="month")
        items = self.client.v1.checkout.sessions.create.call_args.kwargs["params"]["line_items"]
        self.assertEqual(items, [{"price": "price_month", "quantity": 1}, {"price": "price_extra"}])

    async def test_customer_is_idempotent_per_account(self) -> None:
        self.client.v1.customers.create.return_value = {"id": "cus_9"}
        self.assertEqual(await self.gateway.create_customer("acct-1", "a@b.test"), "cus_9")
        call = self.client.v1.customers.create.call_args.kwargs
        self.assertEqual(call["options"], {"idempotency_key": "vl-customer-acct-1"})
        self.assertEqual(call["params"]["metadata"], {"account_id": "acct-1"})

    async def test_portal_returns_to_the_account_view(self) -> None:
        self.client.v1.billing_portal.sessions.create.return_value = {"url": "https://billing.stripe.com/p/1"}
        self.assertEqual(await self.gateway.create_portal_session("cus_1"), "https://billing.stripe.com/p/1")
        params = self.client.v1.billing_portal.sessions.create.call_args.kwargs["params"]
        self.assertEqual(params, {"customer": "cus_1", "return_url": "https://videolens.test/app?view=account"})

    async def test_a_stripe_error_becomes_a_provider_error(self) -> None:
        self.client.v1.customers.create.side_effect = stripe.APIConnectionError("no route")
        with self.assertRaises(BillingProviderError) as caught:
            await self.gateway.create_customer("acct-1", None)
        self.assertIn("APIConnectionError", caught.exception.log_detail)
        self.assertNotIn("no route", str(caught.exception))

    async def test_prices_are_read_and_cached(self) -> None:
        amounts = {"price_month": 1200, "price_year": 12000, "price_extra": 15}
        self.client.v1.prices.retrieve.side_effect = lambda price_id: {"unit_amount": amounts[price_id], "currency": "USD"}
        prices = await self.gateway.prices()
        self.assertEqual((prices.month.amount, prices.year.amount, prices.extra_run.amount), (1200, 12000, 15))
        self.assertEqual(prices.month.currency, "usd")
        await self.gateway.prices()
        self.assertEqual(self.client.v1.prices.retrieve.call_count, 3)

    async def test_prices_never_raise(self) -> None:
        self.client.v1.prices.retrieve.side_effect = stripe.APIConnectionError("down")
        prices = await self.gateway.prices()
        self.assertEqual((prices.month, prices.year, prices.extra_run), (None, None, None))

    async def test_subscription_snapshot_from_the_base_item(self) -> None:
        end = 1_800_000_000
        self.client.v1.subscriptions.retrieve.return_value = {
            "id": "sub_1",
            "customer": "cus_1",
            "status": "active",
            "cancel_at_period_end": False,
            "cancel_at": None,
            "metadata": {"account_id": "acct-1"},
            "items": {
                "data": [
                    {"price": {"id": "price_extra", "recurring": {"interval": "month", "usage_type": "metered"}}, "current_period_end": 1},
                    {"price": {"id": "price_year", "recurring": {"interval": "year", "usage_type": "licensed"}}, "current_period_end": end},
                ]
            },
        }
        snapshot = await self.gateway.get_subscription("sub_1")
        self.assertEqual(
            (snapshot.subscription_id, snapshot.customer_id, snapshot.status, snapshot.price_id, snapshot.interval),
            ("sub_1", "cus_1", "active", "price_year", "year"),
        )
        self.assertEqual(snapshot.current_period_end, datetime.fromtimestamp(end, tz=timezone.utc))
        self.assertFalse(snapshot.cancel_at_period_end)
        self.assertEqual(snapshot.account_id, "acct-1")

    async def test_cancel_is_immediate_without_proration(self) -> None:
        self.client.v1.subscriptions.retrieve.return_value = {"id": "sub_1", "status": "active"}
        await self.gateway.cancel_subscription("sub_1")
        self.client.v1.subscriptions.cancel.assert_called_once_with(
            "sub_1", params={"invoice_now": True, "prorate": False}
        )

    async def test_cancel_skips_an_ended_or_missing_subscription(self) -> None:
        self.client.v1.subscriptions.retrieve.return_value = {"id": "sub_1", "status": "canceled"}
        await self.gateway.cancel_subscription("sub_1")
        self.client.v1.subscriptions.retrieve.side_effect = stripe.InvalidRequestError(
            "No such subscription", "id", code="resource_missing"
        )
        await self.gateway.cancel_subscription("sub_1")
        self.client.v1.subscriptions.cancel.assert_not_called()

    async def test_cancel_failure_raises(self) -> None:
        self.client.v1.subscriptions.retrieve.return_value = {"id": "sub_1", "status": "active"}
        self.client.v1.subscriptions.cancel.side_effect = stripe.APIConnectionError("down")
        with self.assertRaises(BillingProviderError):
            await self.gateway.cancel_subscription("sub_1")

    async def test_meter_event_identified_by_run_id(self) -> None:
        completed = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        await self.gateway.report_extra_run(
            ExtraRunCharge(run_id="run-1", account_id="acct-1", stripe_customer_id="cus_1", completed_at=completed)
        )
        params = self.client.v1.billing.meter_events.create.call_args.kwargs["params"]
        self.assertEqual(
            params,
            {
                "event_name": "videolens_extra_run",
                "identifier": "run-1",
                "timestamp": int(completed.timestamp()),
                "payload": {"stripe_customer_id": "cus_1", "value": "1"},
            },
        )

    async def test_a_duplicate_meter_event_counts_as_reported(self) -> None:
        self.client.v1.billing.meter_events.create.side_effect = stripe.InvalidRequestError(
            "An event with identifier run-1 already exists", None, code="duplicate_meter_event"
        )
        charge = ExtraRunCharge(
            run_id="run-1", account_id="a", stripe_customer_id="cus_1", completed_at=datetime.now(timezone.utc)
        )
        await self.gateway.report_extra_run(charge)
        self.client.v1.billing.meter_events.create.side_effect = stripe.APIConnectionError("down")
        with self.assertRaises(BillingProviderError):
            await self.gateway.report_extra_run(charge)


class WebhookParsingTests(unittest.TestCase):
    """Real signature verification (stripe.Webhook.construct_event), offline."""

    def setUp(self) -> None:
        self.gateway = StripeBillingGateway(_settings())

    def _event(self, obj: dict, kind: str) -> bytes:
        return json.dumps({"id": "evt_1", "object": "event", "type": kind, "data": {"object": obj}}).encode()

    def test_a_forged_or_missing_signature_is_refused(self) -> None:
        payload = self._event({"object": "subscription", "id": "sub_1", "customer": "cus_1"}, "customer.subscription.updated")
        for signature in ("", "t=1,v1=deadbeef", _signed(payload, "whsec_other")):
            with self.assertRaises(WebhookSignatureError):
                self.gateway.parse_webhook(payload, signature)

    def test_subscription_event(self) -> None:
        payload = self._event(
            {"object": "subscription", "id": "sub_1", "customer": "cus_1", "metadata": {"account_id": "acct-1"}},
            "customer.subscription.updated",
        )
        event = self.gateway.parse_webhook(payload, _signed(payload))
        self.assertEqual(
            (event.event_id, event.type, event.customer_id, event.subscription_id, event.account_id),
            ("evt_1", "customer.subscription.updated", "cus_1", "sub_1", "acct-1"),
        )

    def test_checkout_session_event(self) -> None:
        payload = self._event(
            {
                "object": "checkout.session",
                "id": "cs_1",
                "mode": "subscription",
                "customer": "cus_1",
                "subscription": "sub_1",
                "client_reference_id": "acct-1",
            },
            "checkout.session.completed",
        )
        event = self.gateway.parse_webhook(payload, _signed(payload))
        self.assertEqual((event.subscription_id, event.account_id), ("sub_1", "acct-1"))

    def test_invoice_event_basil_shape(self) -> None:
        payload = self._event(
            {
                "object": "invoice",
                "id": "in_1",
                "customer": "cus_1",
                "parent": {"subscription_details": {"subscription": "sub_1", "metadata": {"account_id": "acct-1"}}},
            },
            "invoice.payment_failed",
        )
        event = self.gateway.parse_webhook(payload, _signed(payload))
        self.assertEqual((event.customer_id, event.subscription_id, event.account_id), ("cus_1", "sub_1", "acct-1"))


if __name__ == "__main__":
    unittest.main()
