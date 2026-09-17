"""BillingGateway adapter over Stripe.

Config-gated: with no `STRIPE_SECRET_KEY` the adapter reports `enabled` False
and every money-shaped call raises `BillingNotConfiguredError`. The Stripe
SDK's synchronous client runs in a worker thread; the async variants of the
same calls exist but change shape between SDK majors, and a thread costs
nothing at this call volume.

Plans map to Stripe prices through `STRIPE_PRICE_PRO` / `_STUDIO` / `_SCALE`;
overage minutes are reported to a Stripe Meter named by
`STRIPE_METER_EVENT_NAME`. Every subscription price is expected to be a
seat-based recurring price, and the meter a separate metered price on the
same subscription with the plan's included minutes configured as a free
tier - so the invoice, not this code, decides what an extra minute costs.
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from ...domain.entities import BillingEvent, BillingEventKind, Workspace
from ...domain.entitlements import Plan
from ...domain.errors import BillingNotConfiguredError, WebhookVerificationError
from ..config import Settings

logger = logging.getLogger("videolens")

_ENDED_STATUSES = frozenset({"canceled", "unpaid", "incomplete_expired"})


class StripeBillingGateway:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None

    @property
    def enabled(self) -> bool:
        return self._settings.billing_enabled

    def _price_for(self, plan: Plan) -> str:
        price = {
            Plan.PRO: self._settings.stripe_price_pro,
            Plan.STUDIO: self._settings.stripe_price_studio,
            Plan.SCALE: self._settings.stripe_price_scale,
        }.get(plan, "").strip()
        if not price:
            raise BillingNotConfiguredError(f"No Stripe price is configured for the {plan.value} plan.")
        return price

    def _plan_for_price(self, price_id: str | None) -> Plan | None:
        if not price_id:
            return None
        for plan in (Plan.PRO, Plan.STUDIO, Plan.SCALE):
            if price_id == getattr(self._settings, f"stripe_price_{plan.value}", "").strip():
                return plan
        return None

    def _stripe(self):
        if not self.enabled:
            raise BillingNotConfiguredError("Paid plans are not available on this deployment yet.")
        if self._client is None:
            import stripe

            self._client = stripe.StripeClient(self._settings.stripe_secret_key)
        return self._client

    async def create_checkout_url(
        self,
        *,
        workspace: Workspace,
        plan: Plan,
        customer_email: str | None,
        success_url: str,
        cancel_url: str,
    ) -> str:
        client = self._stripe()
        line_items = [{"price": self._price_for(plan), "quantity": 1}]
        meter_price = self._settings.stripe_price_overage.strip()
        if meter_price:
            line_items.append({"price": meter_price})
        params: dict = {
            "mode": "subscription",
            "line_items": line_items,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": workspace.workspace_id,
            "allow_promotion_codes": True,
            "subscription_data": {"metadata": {"workspace_id": workspace.workspace_id, "plan": plan.value}},
            "metadata": {"workspace_id": workspace.workspace_id, "plan": plan.value},
        }
        if workspace.stripe_customer_id:
            params["customer"] = workspace.stripe_customer_id
        elif customer_email:
            params["customer_email"] = customer_email
        session = await asyncio.to_thread(client.v1.checkout.sessions.create, params)
        return session.url

    async def create_portal_url(self, *, customer_id: str, return_url: str) -> str:
        client = self._stripe()
        session = await asyncio.to_thread(
            client.v1.billing_portal.sessions.create,
            {"customer": customer_id, "return_url": return_url},
        )
        return session.url

    def parse_webhook(self, payload: bytes, signature: str) -> BillingEvent:
        if not self.enabled or not self._settings.stripe_webhook_secret.strip():
            raise BillingNotConfiguredError("Stripe webhooks are not configured.")
        import stripe

        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self._settings.stripe_webhook_secret.strip()
            )
        except Exception as exc:  # noqa: BLE001 - every failure is a bad request
            raise WebhookVerificationError("Webhook signature could not be verified.") from exc
        return self.translate_event(event["id"], event["type"], event["data"]["object"])

    def translate_event(self, event_id: str, event_type: str, obj: dict) -> BillingEvent:
        """Reduce a Stripe event to a `BillingEvent`. Public so the mapping
        can be tested without a signed payload."""
        if event_type == "checkout.session.completed":
            metadata = obj.get("metadata") or {}
            return BillingEvent(
                kind=BillingEventKind.SUBSCRIPTION_STARTED,
                event_id=event_id,
                customer_id=_as_id(obj.get("customer")),
                subscription_id=_as_id(obj.get("subscription")),
                workspace_id=obj.get("client_reference_id") or metadata.get("workspace_id"),
                plan=_plan(metadata.get("plan")),
            )
        if event_type in ("customer.subscription.created", "customer.subscription.updated"):
            status = obj.get("status")
            kind = (
                BillingEventKind.SUBSCRIPTION_ENDED
                if status in _ENDED_STATUSES
                else BillingEventKind.SUBSCRIPTION_UPDATED
            )
            return self._subscription_event(kind, event_id, obj)
        if event_type == "customer.subscription.deleted":
            return self._subscription_event(BillingEventKind.SUBSCRIPTION_ENDED, event_id, obj)
        return BillingEvent(kind=BillingEventKind.IGNORED, event_id=event_id)

    def _subscription_event(self, kind: BillingEventKind, event_id: str, obj: dict) -> BillingEvent:
        items = ((obj.get("items") or {}).get("data")) or []
        plan = None
        period_start = _ts(obj.get("current_period_start"))
        period_end = _ts(obj.get("current_period_end"))
        for item in items:
            price = item.get("price") or {}
            plan = plan or self._plan_for_price(price.get("id"))
            # Newer API versions carry the period on each item instead.
            period_start = period_start or _ts(item.get("current_period_start"))
            period_end = period_end or _ts(item.get("current_period_end"))
        metadata = obj.get("metadata") or {}
        return BillingEvent(
            kind=kind,
            event_id=event_id,
            customer_id=_as_id(obj.get("customer")),
            subscription_id=obj.get("id"),
            workspace_id=metadata.get("workspace_id"),
            plan=plan or _plan(metadata.get("plan")),
            period_start=period_start,
            period_end=period_end,
        )

    async def report_usage(self, *, customer_id: str, minutes: Decimal, run_id: str) -> str | None:
        client = self._stripe()
        event_name = self._settings.stripe_meter_event_name.strip()
        if not event_name:
            return None
        result = await asyncio.to_thread(
            client.v2.billing.meter_events.create,
            {
                "event_name": event_name,
                "identifier": run_id,
                "payload": {"stripe_customer_id": customer_id, "value": str(minutes)},
            },
        )
        return getattr(result, "identifier", None) or run_id


def _as_id(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.get("id") if isinstance(value, dict) else getattr(value, "id", None)


def _plan(value) -> Plan | None:
    try:
        return Plan(value) if value else None
    except ValueError:
        return None


def _ts(value) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)
