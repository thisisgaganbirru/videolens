"""`POST /api/billing/webhook`: Stripe tells us a subscription changed.

The event is only a nudge. Whatever it says, the subscription is read fresh
from Stripe and stored as Stripe has it now, so events arriving out of
order, twice, or late all converge on the same row. An event id is recorded
only after it was handled: a failure answers 500 and Stripe sends it again
(its retries run for days); a repeat of a handled one is a no-op. Only ids
are logged, never an email, an address or a card.
"""

import logging

from ..domain.entities import BillingWebhookEvent
from ..domain.errors import BillingNotConfiguredError
from .billing import BillingPlans

logger = logging.getLogger("videolens")

# The events the plan listens to. The Stripe webhook endpoint should send
# these; anything else it sends is acknowledged and ignored.
HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
        "invoice.paid",
        "invoice.payment_failed",
    }
)


class HandleBillingWebhookUseCase:
    def __init__(self, *, plans: BillingPlans) -> None:
        self._plans = plans

    async def execute(self, payload: bytes, signature: str) -> str:
        """What happened ("handled" | "duplicate" | "ignored"), for tests and
        the log. Raises `WebhookSignatureError` (400) before reading anything
        when the signature does not verify."""
        if not self._plans.enabled:
            raise BillingNotConfiguredError()
        event = self._plans.gateway.parse_webhook(payload, signature)
        accounts = self._plans.accounts
        if await accounts.event_seen(event.event_id):
            return "duplicate"
        outcome = "ignored"
        if event.type in HANDLED_EVENTS:
            outcome = await self._sync(event)
        await accounts.mark_event(event.event_id, event.type)
        logger.info("Stripe event %s (%s): %s", event.event_id, event.type, outcome)
        return outcome

    async def _sync(self, event: BillingWebhookEvent) -> str:
        accounts = self._plans.accounts
        account = await accounts.by_customer(event.customer_id) if event.customer_id else None
        if account is None and event.account_id:
            candidate = await accounts.get(event.account_id)
            # Only for the same customer: a metadata id alone must never move
            # a subscription onto another account.
            if candidate is not None and (not event.customer_id or candidate.stripe_customer_id == event.customer_id):
                account = candidate
        if account is None:
            # A deleted account, or a customer this app did not create.
            logger.warning("Stripe event %s names no known account (customer %s)", event.event_id, event.customer_id)
            return "ignored"
        if not event.subscription_id:
            return "ignored"
        snapshot = await self._plans.gateway.get_subscription(event.subscription_id)
        if snapshot.customer_id != account.stripe_customer_id:
            logger.warning(
                "Stripe event %s: subscription %s belongs to another customer",
                event.event_id,
                snapshot.subscription_id,
            )
            return "ignored"
        applied = await accounts.apply_subscription(account.account_id, snapshot)
        if applied:
            logger.info("Account %s subscription %s is %s", account.account_id, snapshot.subscription_id, snapshot.status)
        return "handled" if applied else "ignored"
