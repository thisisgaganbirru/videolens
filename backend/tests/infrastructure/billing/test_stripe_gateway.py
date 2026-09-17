"""The Stripe adapter without Stripe: the config gate and the event mapping.
Both are the parts a misconfiguration would break; the SDK calls themselves
are one-liners against a client that is not worth mocking."""

import unittest
from datetime import datetime, timezone

from app.domain.entities import BillingEventKind
from app.domain.entitlements import Plan
from app.domain.errors import BillingNotConfiguredError, WebhookVerificationError
from app.infrastructure.billing.stripe_gateway import StripeBillingGateway
from app.infrastructure.config import Settings

from tests.application.fakes import make_workspace


def _settings(**overrides) -> Settings:
    fields = dict(
        stripe_secret_key="sk_test_123",
        stripe_webhook_secret="whsec_test",
        stripe_price_pro="price_pro",
        stripe_price_studio="price_studio",
        stripe_price_scale="price_scale",
    )
    fields.update(overrides)
    return Settings(_env_file=None, **fields)


class DisabledGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gateway = StripeBillingGateway(Settings(_env_file=None))

    def test_reports_disabled_without_a_secret_key(self) -> None:
        self.assertFalse(self.gateway.enabled)
        self.assertTrue(StripeBillingGateway(_settings()).enabled)

    async def test_every_money_call_refuses(self) -> None:
        with self.assertRaises(BillingNotConfiguredError):
            await self.gateway.create_checkout_url(
                workspace=make_workspace(),
                plan=Plan.PRO,
                customer_email=None,
                success_url="https://a",
                cancel_url="https://b",
            )
        with self.assertRaises(BillingNotConfiguredError):
            await self.gateway.create_portal_url(customer_id="cus_1", return_url="https://a")
        with self.assertRaises(BillingNotConfiguredError):
            await self.gateway.report_usage(customer_id="cus_1", minutes=1, run_id="r")
        with self.assertRaises(BillingNotConfiguredError):
            self.gateway.parse_webhook(b"{}", "sig")

    def test_webhooks_need_their_own_secret(self) -> None:
        gateway = StripeBillingGateway(_settings(stripe_webhook_secret=""))
        with self.assertRaises(BillingNotConfiguredError):
            gateway.parse_webhook(b"{}", "sig")


class WebhookVerificationTests(unittest.TestCase):
    def test_a_bad_signature_is_a_verification_error(self) -> None:
        gateway = StripeBillingGateway(_settings())
        with self.assertRaises(WebhookVerificationError):
            gateway.parse_webhook(b'{"id": "evt_1"}', "t=1,v1=deadbeef")


class TranslateEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = StripeBillingGateway(_settings())

    def test_checkout_completed_starts_a_subscription_for_the_referenced_workspace(self) -> None:
        event = self.gateway.translate_event(
            "evt_1",
            "checkout.session.completed",
            {
                "customer": "cus_1",
                "subscription": {"id": "sub_1"},
                "client_reference_id": "ws-pro",
                "metadata": {"plan": "pro"},
            },
        )

        self.assertIs(event.kind, BillingEventKind.SUBSCRIPTION_STARTED)
        self.assertEqual(event.customer_id, "cus_1")
        self.assertEqual(event.subscription_id, "sub_1")
        self.assertEqual(event.workspace_id, "ws-pro")
        self.assertIs(event.plan, Plan.PRO)

    def test_subscription_updated_maps_the_price_to_a_plan_and_carries_the_period(self) -> None:
        event = self.gateway.translate_event(
            "evt_2",
            "customer.subscription.updated",
            {
                "id": "sub_1",
                "status": "active",
                "customer": {"id": "cus_1"},
                "current_period_start": 1_756_684_800,
                "current_period_end": 1_759_276_800,
                "items": {"data": [{"price": {"id": "price_studio"}}]},
                "metadata": {"workspace_id": "ws-pro"},
            },
        )

        self.assertIs(event.kind, BillingEventKind.SUBSCRIPTION_UPDATED)
        self.assertEqual(event.customer_id, "cus_1")
        self.assertEqual(event.workspace_id, "ws-pro")
        self.assertIs(event.plan, Plan.STUDIO)
        self.assertEqual(event.period_start, datetime(2025, 9, 1, tzinfo=timezone.utc))
        self.assertEqual(event.period_end, datetime(2025, 10, 1, tzinfo=timezone.utc))

    def test_period_is_read_from_the_item_on_newer_api_versions(self) -> None:
        event = self.gateway.translate_event(
            "evt_3",
            "customer.subscription.created",
            {
                "id": "sub_1",
                "status": "trialing",
                "customer": "cus_1",
                "items": {
                    "data": [
                        {
                            "price": {"id": "price_overage"},
                            "current_period_start": 100,
                            "current_period_end": 200,
                        },
                        {"price": {"id": "price_pro"}},
                    ]
                },
            },
        )

        self.assertIs(event.plan, Plan.PRO)
        self.assertEqual(event.period_start, datetime.fromtimestamp(100, tz=timezone.utc))
        self.assertEqual(event.period_end, datetime.fromtimestamp(200, tz=timezone.utc))

    def test_unknown_prices_fall_back_to_the_plan_in_metadata(self) -> None:
        event = self.gateway.translate_event(
            "evt_4",
            "customer.subscription.updated",
            {
                "id": "sub_1",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_other"}}]},
                "metadata": {"plan": "scale"},
            },
        )
        self.assertIs(event.plan, Plan.SCALE)

        nonsense = self.gateway.translate_event(
            "evt_5", "customer.subscription.updated", {"id": "sub_1", "metadata": {"plan": "gold"}}
        )
        self.assertIsNone(nonsense.plan)

    def test_terminal_statuses_and_deletion_end_the_subscription(self) -> None:
        for status in ("canceled", "unpaid", "incomplete_expired"):
            event = self.gateway.translate_event(
                "evt", "customer.subscription.updated", {"id": "sub_1", "status": status}
            )
            self.assertIs(event.kind, BillingEventKind.SUBSCRIPTION_ENDED, status)

        deleted = self.gateway.translate_event(
            "evt_6", "customer.subscription.deleted", {"id": "sub_1", "customer": "cus_1"}
        )
        self.assertIs(deleted.kind, BillingEventKind.SUBSCRIPTION_ENDED)
        self.assertEqual(deleted.subscription_id, "sub_1")

    def test_past_due_is_still_a_live_subscription(self) -> None:
        event = self.gateway.translate_event(
            "evt_7", "customer.subscription.updated", {"id": "sub_1", "status": "past_due"}
        )
        self.assertIs(event.kind, BillingEventKind.SUBSCRIPTION_UPDATED)

    def test_everything_else_is_ignored(self) -> None:
        event = self.gateway.translate_event("evt_8", "invoice.paid", {"id": "in_1"})
        self.assertIs(event.kind, BillingEventKind.IGNORED)
        self.assertEqual(event.event_id, "evt_8")


if __name__ == "__main__":
    unittest.main()
