"""`/api/billing*` end to end through FastAPI: the exact contract the
frontend builds against, who may call what, the webhook's signature check
and idempotency, and billing-off parity. The real StripeBillingGateway runs
over a mocked StripeClient (never the network); webhooks are signed locally
with the test secret."""

import hashlib
import hmac
import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from unittest.mock import patch

import stripe
from starlette.testclient import TestClient

from app.application.billing import BillingPlans
from app.application.delete_account import DeleteAccountUseCase
from app.application.get_billing import GetBillingUseCase
from app.application.get_free_runs import GetFreeRunsUseCase
from app.application.handle_billing_webhook import HandleBillingWebhookUseCase
from app.application.identify_caller import IdentifyCallerUseCase
from app.application.open_billing_portal import OpenBillingPortalUseCase
from app.application.start_checkout import StartCheckoutUseCase
from app.container import container
from app.infrastructure.billing.stripe_gateway import StripeBillingGateway
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_deleter import InMemoryAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.account_free_runs import InMemoryAccountFreeRuns
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
from app.infrastructure.persistence.billing_store import InMemoryBillingAccounts, InMemoryExtraRunLedger
from app.infrastructure.persistence.run_repository import RunStore
from app.interface.api.app import app

SECRET = "whsec_test_secret"
TOKEN = {"Authorization": "Bearer eyJhbGciOi.payload.signature"}
ANON = {"X-Client-ID": "test-client-0123456789"}


def _settings(enabled: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key="k",
        stripe_secret_key="sk_test_123" if enabled else "",
        stripe_webhook_secret=SECRET,
        stripe_price_monthly="price_month",
        stripe_price_yearly="price_year",
        stripe_price_extra_run="price_extra",
        allowed_origins="https://videolens.test",
        free_runs_per_account_daily=10,
    )


def _signed(payload: bytes) -> str:
    timestamp = int(time.time())
    signature = hmac.new(SECRET.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


class _Verifier:
    def __init__(self, claims: dict) -> None:
        self.claims = claims

    def decode(self, token: str) -> dict:
        return dict(self.claims)


class BillingRoutesTests(unittest.TestCase):
    enabled = True

    def setUp(self) -> None:
        settings = _settings(self.enabled)
        self.stripe = mock.MagicMock()
        amounts = {"price_month": 1200, "price_year": 12000, "price_extra": 15}
        self.stripe.v1.prices.retrieve.side_effect = lambda price_id: {"unit_amount": amounts[price_id], "currency": "usd"}
        self.stripe.v1.customers.create.return_value = {"id": "cus_1"}
        self.stripe.v1.checkout.sessions.create.return_value = {"url": "https://checkout.stripe.com/c/1"}
        self.stripe.v1.billing_portal.sessions.create.return_value = {"url": "https://billing.stripe.com/p/1"}
        self.gateway = StripeBillingGateway(settings, client=self.stripe)
        self.directory = InMemoryAccountDirectory()
        keys = InMemoryApiKeyRepository()
        self.billing_accounts = InMemoryBillingAccounts(settings)
        ledger = InMemoryExtraRunLedger(settings)
        self.account_runs = InMemoryAccountFreeRuns(settings)
        plans = BillingPlans(
            gateway=self.gateway, accounts=self.billing_accounts, ledger=ledger, paid_runs_per_month=100
        )
        self.plans = plans
        replacements = {
            "identify_caller_use_case": IdentifyCallerUseCase(
                accounts=self.directory,
                api_keys=keys,
                verifier=_Verifier({"sub": "user-123", "email": "a@b.test", "role": "authenticated"}),
                allow_anonymous=True,
            ),
            "get_billing_use_case": GetBillingUseCase(plans=plans, account_free_runs=self.account_runs),
            "start_checkout_use_case": StartCheckoutUseCase(plans=plans),
            "open_billing_portal_use_case": OpenBillingPortalUseCase(plans=plans),
            "handle_billing_webhook_use_case": HandleBillingWebhookUseCase(plans=plans),
            "get_free_runs_use_case": GetFreeRunsUseCase(
                free_runs=container.free_runs,
                device_tokens=container.device_tokens,
                account_free_runs=self.account_runs,
                billing=plans,
            ),
            "delete_account_use_case": DeleteAccountUseCase(
                accounts=self.directory,
                deleter=InMemoryAccountDeleter(
                    settings,
                    accounts=self.directory,
                    api_keys=keys,
                    billing_accounts=self.billing_accounts,
                    extra_runs=ledger,
                ),
                api_keys=keys,
                runs=RunStore(Settings(_env_file=None)),
                billing=plans,
            ),
        }
        for name, value in replacements.items():
            patcher = patch.object(container, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def _account_id(self) -> str:
        self.client.get("/api/billing", headers=TOKEN)  # first sight creates the account
        return next(iter(self.directory._accounts.values())).account_id

    def _subscription(self, status: str = "active") -> dict:
        end = int((datetime.now(timezone.utc) + timedelta(days=20)).timestamp())
        return {
            "id": "sub_1",
            "customer": "cus_1",
            "status": status,
            "cancel_at_period_end": False,
            "metadata": {},
            "items": {"data": [{"price": {"id": "price_month", "recurring": {"interval": "month"}}, "current_period_end": end}]},
        }

    def _webhook(self, event_id: str, kind: str = "customer.subscription.updated", signature: str | None = None):
        payload = json.dumps(
            {
                "id": event_id,
                "object": "event",
                "type": kind,
                "data": {"object": {"object": "subscription", "id": "sub_1", "customer": "cus_1"}},
            }
        ).encode()
        return self.client.post(
            "/api/billing/webhook",
            content=payload,
            headers={"Stripe-Signature": signature if signature is not None else _signed(payload)},
        )


class EnabledBillingRoutesTests(BillingRoutesTests):
    def test_anonymous_is_401(self) -> None:
        # Exactly like /api/me: an anonymous caller (X-Client-ID) is 401.
        self.assertEqual(self.client.get("/api/billing", headers=ANON).status_code, 401)
        self.assertEqual(
            self.client.get("/api/billing").status_code, self.client.get("/api/me").status_code
        )

    def test_free_account_contract(self) -> None:
        response = self.client.get("/api/billing", headers=TOKEN)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            body,
            {
                "enabled": True,
                "plan": "free",
                "status": None,
                "interval": None,
                "current_period_end": None,
                "cancel_at_period_end": False,
                "runs": {"limit": 10, "used": 0, "period": "day"},
                "prices": {
                    "month": {"amount": 1200, "currency": "usd"},
                    "year": {"amount": 12000, "currency": "usd"},
                    "extra_run": {"amount": 15, "currency": "usd"},
                },
            },
        )

    def test_checkout_then_409_once_subscribed(self) -> None:
        response = self.client.post("/api/billing/checkout", headers=TOKEN, json={"interval": "month"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"url": "https://checkout.stripe.com/c/1"})

        self.stripe.v1.subscriptions.retrieve.return_value = self._subscription()
        self.assertEqual(self._webhook("evt_1", "checkout.session.completed").status_code, 200)

        again = self.client.post("/api/billing/checkout", headers=TOKEN, json={"interval": "year"})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["code"], "already_subscribed")
        self.assertTrue(again.json()["detail"])

        body = self.client.get("/api/billing", headers=TOKEN).json()
        self.assertEqual((body["plan"], body["status"], body["interval"]), ("paid", "active", "month"))
        self.assertEqual(body["runs"], {"limit": 100, "used": 0, "period": "month"})

    def test_an_invalid_interval_is_422(self) -> None:
        response = self.client.post("/api/billing/checkout", headers=TOKEN, json={"interval": "week"})
        self.assertEqual(response.status_code, 422)

    def test_portal_404_then_url(self) -> None:
        response = self.client.post("/api/billing/portal", headers=TOKEN)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "no_billing_account")
        self.client.post("/api/billing/checkout", headers=TOKEN, json={"interval": "month"})
        response = self.client.post("/api/billing/portal", headers=TOKEN)
        self.assertEqual(response.json(), {"url": "https://billing.stripe.com/p/1"})

    def test_checkout_and_portal_need_a_person(self) -> None:
        for path in ("/api/billing/checkout", "/api/billing/portal"):
            response = self.client.post(path, headers=ANON, json={"interval": "month"})
            self.assertEqual(response.status_code, 401, path)

    def test_stripe_down_is_503_with_a_code(self) -> None:
        self.stripe.v1.customers.create.side_effect = stripe.APIConnectionError("down")
        response = self.client.post("/api/billing/checkout", headers=TOKEN, json={"interval": "month"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "billing_unavailable")

    def test_webhook_signature_failure_is_400(self) -> None:
        response = self._webhook("evt_1", signature="t=1,v1=forged")
        self.assertEqual(response.status_code, 400)
        self.stripe.v1.subscriptions.retrieve.assert_not_called()

    def test_webhook_is_idempotent(self) -> None:
        self.client.post("/api/billing/checkout", headers=TOKEN, json={"interval": "month"})
        self.stripe.v1.subscriptions.retrieve.return_value = self._subscription()
        self.assertEqual(self._webhook("evt_1").json(), {"received": True})
        self.assertEqual(self._webhook("evt_1").json(), {"received": True})
        self.assertEqual(self.stripe.v1.subscriptions.retrieve.call_count, 1)

    def test_free_runs_gains_plan_and_overage(self) -> None:
        body = self.client.get("/api/free-runs", headers=TOKEN).json()
        self.assertEqual((body["plan"], body["overage"], body["limit"], body["period"]), ("free", False, 10, "day"))
        self.assertRegex(body["resets_at"], r"T00:00:00(Z|\+00:00)$")
        self.client.post("/api/billing/checkout", headers=TOKEN, json={"interval": "month"})
        self.stripe.v1.subscriptions.retrieve.return_value = self._subscription()
        self._webhook("evt_1")
        body = self.client.get("/api/free-runs", headers=TOKEN).json()
        self.assertEqual((body["plan"], body["overage"], body["limit"], body["remaining"]), ("paid", True, 100, 100))
        # The paid plan's included runs are still monthly.
        self.assertEqual(body["period"], "month")
        self.assertRegex(body["resets_at"], r"^\d{4}-\d{2}-01T00:00:00(Z|\+00:00)$")
        # Anonymous: the fields it always had, nothing more.
        anonymous = self.client.get("/api/free-runs").json()
        self.assertNotIn("plan", anonymous)
        self.assertNotIn("overage", anonymous)

    def test_deleting_the_account_cancels_the_subscription(self) -> None:
        self.client.post("/api/billing/checkout", headers=TOKEN, json={"interval": "month"})
        self.stripe.v1.subscriptions.retrieve.return_value = self._subscription()
        self._webhook("evt_1")
        self.stripe.v1.subscriptions.cancel.side_effect = stripe.APIConnectionError("down")
        refused = self.client.delete("/api/me", headers=TOKEN)
        self.assertEqual(refused.status_code, 503)
        self.assertEqual(refused.json()["code"], "subscription_cancel_failed")
        self.assertTrue(self.directory._accounts)

        self.stripe.v1.subscriptions.cancel.side_effect = None
        self.assertEqual(self.client.delete("/api/me", headers=TOKEN).status_code, 204)
        self.stripe.v1.subscriptions.cancel.assert_called_with("sub_1", params={"invoice_now": True, "prorate": False})


class DisabledBillingRoutesTests(BillingRoutesTests):
    enabled = False

    def test_billing_is_just_disabled(self) -> None:
        response = self.client.get("/api/billing", headers=TOKEN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"enabled": False})
        self.assertEqual(self.client.get("/api/billing", headers=ANON).status_code, 401)

    def test_checkout_portal_and_webhook_are_503(self) -> None:
        for path in ("/api/billing/checkout", "/api/billing/portal"):
            response = self.client.post(path, headers=TOKEN, json={"interval": "month"})
            self.assertEqual(response.status_code, 503, path)
            self.assertEqual(response.json()["code"], "billing_disabled")
        self.assertEqual(self._webhook("evt_1").status_code, 503)
        self.stripe.v1.customers.create.assert_not_called()

    def test_free_runs_is_the_free_plan(self) -> None:
        body = self.client.get("/api/free-runs", headers=TOKEN).json()
        self.assertEqual((body["plan"], body["overage"], body["limit"]), ("free", False, 10))


class CapabilityRowTests(unittest.TestCase):
    def test_the_billing_row_exists(self) -> None:
        body = TestClient(app).get("/api/capabilities").json()
        rows = {row["name"]: row for row in body["capabilities"]}
        self.assertIn("billing", rows)
        self.assertIn(rows["billing"]["state"], ("ok", "disabled", "degraded"))


del BillingRoutesTests

if __name__ == "__main__":
    unittest.main()
