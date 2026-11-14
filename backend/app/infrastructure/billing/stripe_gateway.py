"""BillingGateway adapter: Stripe (docs/backend/billing.md).

Hosted Checkout and the Customer Portal only, so no card ever touches this
server or the frontend. The SDK is synchronous; every call runs in a thread
so the event loop is never blocked on Stripe. Every Stripe object is turned
into a plain dict at once (`to_dict`) and reduced to a domain record here:
the application never sees a Stripe type, and nothing but ids is logged.

The plan's shape in Stripe, which the owner creates in the dashboard:

- one Product with two licensed recurring Prices (`STRIPE_PRICE_MONTHLY`,
  optional `STRIPE_PRICE_YEARLY`);
- one Billing Meter (`STRIPE_METER_EVENT_NAME`, sum of `value`, customer
  mapped from `stripe_customer_id`) and a monthly metered Price on it
  (`STRIPE_PRICE_EXTRA_RUN`), the per-extra-run amount.

Every subscription carries the base price and the metered price. A yearly
base with a monthly metered price is a mixed-interval subscription, which
Stripe supports in flexible billing mode (API 2025-07-30.basil or later;
this SDK pins a later one), so Checkout asks for `billing_mode=flexible`.
Setting `STRIPE_PRICE_EXTRA_RUN_YEARLY` (a yearly metered price on the same
meter) puts that on yearly subscriptions instead, billed once a year.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from ...domain.entities import BillingPrices, BillingWebhookEvent, ExtraRunCharge, Price, SubscriptionSnapshot
from ...domain.errors import BillingNotConfiguredError, BillingProviderError, WebhookSignatureError
from ..config import Settings

logger = logging.getLogger("videolens")

# Prices change rarely; amounts on screen may lag a dashboard edit by this.
_PRICE_TTL_SECONDS = 3600.0
# After a failed read, try again soon rather than every request.
_PRICE_RETRY_SECONDS = 60.0
_ENDED_STATUSES = frozenset({"canceled", "incomplete_expired"})


def _plain(value: Any) -> Any:
    to_dict = getattr(value, "to_dict", None)
    return to_dict() if callable(to_dict) else value


def _id(value: Any) -> str | None:
    """A Stripe reference is an id string, or the expanded object."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("id")
    return None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _describe(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    status = getattr(exc, "http_status", None)
    return f"{type(exc).__name__} code={code} status={status}"


class StripeBillingGateway:
    def __init__(
        self,
        settings: Settings,
        *,
        client: Any = None,
        construct_event: Callable[..., Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._construct_event = construct_event
        self._clock = clock or time.monotonic
        self._prices: BillingPrices | None = None
        self._prices_until = 0.0

    # ------------------------------------------------------------ config

    @property
    def enabled(self) -> bool:
        return self._settings.billing_configured

    @property
    def yearly_available(self) -> bool:
        return bool(self._settings.stripe_price_yearly.strip())

    @property
    def test_mode(self) -> bool:
        return self._settings.stripe_secret_key.strip().startswith(("sk_test_", "rk_test_"))

    def _stripe(self) -> Any:
        if not self.enabled:
            raise BillingNotConfiguredError()
        if self._client is None:
            import stripe  # imported lazily: billing off never loads the SDK

            self._client = stripe.StripeClient(self._settings.stripe_secret_key.strip(), max_network_retries=2)
        return self._client

    async def _call(self, what: str, fn: Callable[[], Any]) -> Any:
        try:
            return _plain(await asyncio.to_thread(fn))
        except BillingNotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001 - one phone message; the cause in the log
            detail = f"{what}: {_describe(exc)}"
            logger.warning("Stripe call failed (%s)", detail)
            raise BillingProviderError(log_detail=detail) from exc

    def _return_url(self, billing: str | None = None) -> str:
        url = f"{self._settings.billing_return_base}/app?view=account"
        return f"{url}&billing={billing}" if billing else url

    # ------------------------------------------------------------ calls

    async def create_customer(self, account_id: str, email: str | None) -> str:
        client = self._stripe()
        params: dict = {"metadata": {"account_id": account_id}}
        if email:
            # For receipts and the portal; Stripe would ask for it otherwise.
            params["email"] = email
        customer = await self._call(
            "create customer",
            lambda: client.v1.customers.create(params=params, options={"idempotency_key": f"vl-customer-{account_id}"}),
        )
        return customer["id"]

    def _line_items(self, interval: str) -> list[dict]:
        settings = self._settings
        base = settings.stripe_price_yearly if interval == "year" else settings.stripe_price_monthly
        extra = settings.stripe_price_extra_run
        if interval == "year" and settings.stripe_price_extra_run_yearly.strip():
            extra = settings.stripe_price_extra_run_yearly
        # A metered price takes no quantity.
        return [{"price": base.strip(), "quantity": 1}, {"price": extra.strip()}]

    async def create_checkout_session(self, *, customer_id: str, account_id: str, interval: str) -> str:
        client = self._stripe()
        params = {
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": account_id,
            "line_items": self._line_items(interval),
            "success_url": self._return_url("success"),
            "cancel_url": self._return_url("cancel"),
            "metadata": {"account_id": account_id},
            "subscription_data": {
                "metadata": {"account_id": account_id},
                # Mixed intervals (yearly base + monthly metered) need it.
                "billing_mode": {"type": "flexible"},
            },
        }
        session = await self._call("create checkout session", lambda: client.v1.checkout.sessions.create(params=params))
        return session["url"]

    async def create_portal_session(self, customer_id: str) -> str:
        client = self._stripe()
        params = {"customer": customer_id, "return_url": self._return_url()}
        session = await self._call("create portal session", lambda: client.v1.billing_portal.sessions.create(params=params))
        return session["url"]

    async def prices(self) -> BillingPrices:
        if not self.enabled:
            return BillingPrices()
        now = self._clock()
        if self._prices is not None and now < self._prices_until:
            return self._prices
        settings = self._settings
        wanted = {
            "month": settings.stripe_price_monthly,
            "year": settings.stripe_price_yearly,
            "extra_run": settings.stripe_price_extra_run,
        }
        found: dict[str, Price | None] = {}
        failed = False
        for key, price_id in wanted.items():
            if not price_id.strip():
                found[key] = None
                continue
            try:
                found[key] = await self._price(price_id.strip())
            except Exception:  # noqa: BLE001 - logged in _call; shown as null
                found[key] = None
                failed = True
        self._prices = BillingPrices(**found)
        self._prices_until = now + (_PRICE_RETRY_SECONDS if failed else _PRICE_TTL_SECONDS)
        return self._prices

    async def _price(self, price_id: str) -> Price | None:
        client = self._stripe()
        price = await self._call("retrieve price", lambda: client.v1.prices.retrieve(price_id))
        amount = price.get("unit_amount")
        if amount is None and price.get("unit_amount_decimal") is not None:
            try:
                amount = int(round(float(price["unit_amount_decimal"])))
            except (TypeError, ValueError):
                amount = None
        if amount is None:
            # Tiered or custom pricing: not something one number can show.
            return None
        return Price(amount=int(amount), currency=str(price.get("currency") or "usd").lower())

    def parse_webhook(self, payload: bytes, signature: str) -> BillingWebhookEvent:
        if not self.enabled:
            raise BillingNotConfiguredError()
        construct = self._construct_event
        if construct is None:
            import stripe

            construct = stripe.Webhook.construct_event
        try:
            event = _plain(construct(payload, signature, self._settings.stripe_webhook_secret.strip()))
        except Exception as exc:  # noqa: BLE001 - SignatureVerificationError, ValueError (bad JSON)
            raise WebhookSignatureError("Invalid signature.") from exc
        return self._reduce_event(event)

    def _reduce_event(self, event: dict) -> BillingWebhookEvent:
        kind = str(event.get("type") or "")
        obj = (event.get("data") or {}).get("object") or {}
        metadata = obj.get("metadata") or {}
        customer_id = _id(obj.get("customer"))
        subscription_id = None
        account_id = metadata.get("account_id")
        object_type = obj.get("object")
        if object_type == "checkout.session":
            subscription_id = _id(obj.get("subscription")) if obj.get("mode") == "subscription" else None
            account_id = obj.get("client_reference_id") or account_id
        elif object_type == "subscription":
            subscription_id = obj.get("id")
        elif object_type == "invoice":
            # Basil and later: parent.subscription_details.subscription.
            parent = obj.get("parent") or {}
            details = parent.get("subscription_details") or {}
            subscription_id = _id(details.get("subscription")) or _id(obj.get("subscription"))
            account_id = (details.get("metadata") or {}).get("account_id") or account_id
        return BillingWebhookEvent(
            event_id=str(event.get("id") or ""),
            type=kind,
            customer_id=customer_id,
            subscription_id=subscription_id,
            account_id=account_id,
        )

    async def get_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        client = self._stripe()
        subscription = await self._call(
            "retrieve subscription", lambda: client.v1.subscriptions.retrieve(subscription_id)
        )
        return self._snapshot(subscription)

    def _snapshot(self, sub: dict) -> SubscriptionSnapshot:
        settings = self._settings
        base_ids = {settings.stripe_price_monthly.strip(), settings.stripe_price_yearly.strip()} - {""}
        items = ((sub.get("items") or {}).get("data")) or []
        base = next((item for item in items if _id(item.get("price")) in base_ids), None)
        if base is None:
            # Not one of the configured prices (changed in the dashboard):
            # the first licensed item stands in.
            base = next(
                (
                    item
                    for item in items
                    if ((item.get("price") or {}).get("recurring") or {}).get("usage_type") != "metered"
                ),
                items[0] if items else {},
            )
        price = base.get("price") or {}
        recurring = price.get("recurring") or {} if isinstance(price, dict) else {}
        return SubscriptionSnapshot(
            subscription_id=str(sub.get("id")),
            customer_id=_id(sub.get("customer")) or "",
            status=str(sub.get("status") or ""),
            price_id=_id(price),
            interval=recurring.get("interval"),
            # Per item since API 2025-03-31.basil; the top-level field on
            # older versions.
            current_period_end=_timestamp(base.get("current_period_end")) or _timestamp(sub.get("current_period_end")),
            cancel_at_period_end=bool(sub.get("cancel_at_period_end")) or bool(sub.get("cancel_at")),
            account_id=(sub.get("metadata") or {}).get("account_id"),
        )

    async def cancel_subscription(self, subscription_id: str) -> None:
        client = self._stripe()
        try:
            current = await self._call("retrieve subscription", lambda: client.v1.subscriptions.retrieve(subscription_id))
        except BillingProviderError as exc:
            cause = exc.__cause__
            if getattr(cause, "code", None) == "resource_missing":
                return  # already gone in Stripe
            raise
        if current.get("status") in _ENDED_STATUSES:
            return
        # Now, not at period end; no proration credit; usage not yet
        # invoiced (extra runs) goes on a final invoice now.
        await self._call(
            "cancel subscription",
            lambda: client.v1.subscriptions.cancel(subscription_id, params={"invoice_now": True, "prorate": False}),
        )

    async def report_extra_run(self, charge: ExtraRunCharge) -> None:
        client = self._stripe()
        params = {
            "event_name": self._settings.stripe_meter_event_name.strip(),
            "identifier": charge.run_id,
            "timestamp": int(charge.completed_at.timestamp()),
            "payload": {"stripe_customer_id": charge.stripe_customer_id, "value": "1"},
        }
        try:
            await self._call("create meter event", lambda: client.v1.billing.meter_events.create(params=params))
        except BillingProviderError as exc:
            cause = exc.__cause__
            message = str(getattr(cause, "user_message", None) or cause or "").lower()
            if "duplicate" in str(getattr(cause, "code", "") or "") or ("identifier" in message and "already" in message):
                # Stripe already has this run: reported, not a failure.
                return
            raise
