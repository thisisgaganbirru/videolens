# Billing (Stripe)

Subscriptions for the paid plans, the customer portal, the webhook that keeps a workspace's plan in step with Stripe, and per-run usage reporting to a Stripe meter. Config-gated on `STRIPE_SECRET_KEY`: without it every billing route answers 503 `BillingNotConfiguredError` and `GET /api/me` reports `billing_enabled: false`, so the frontend shows the plans without upgrade buttons.

**Files**
- `backend/app/application/billing.py` — `StartCheckoutUseCase`, `OpenBillingPortalUseCase` (both owner-only: `PermissionDeniedError` 403 for members), `ApplyBillingEventUseCase` (idempotent; every event carries the subscription's whole state so replays and reordering land on the same row).
- `backend/app/infrastructure/billing/stripe_gateway.py` — `StripeBillingGateway`, implements `BillingGateway`. Uses `stripe.StripeClient` inside `asyncio.to_thread`; the SDK is imported lazily so an unconfigured deployment never loads it. `translate_event` is the public event mapping so it is testable without a signed payload.
- `backend/app/domain/entities.py` — `BillingEvent`, `BillingEventKind` (`subscription_started|updated|ended|ignored`).
- `backend/app/interface/api/routes.py` — `POST /api/billing/checkout` (`{plan}` → `{url}`), `POST /api/billing/portal` (→ `{url}`), `POST /api/webhooks/stripe` (raw body + `Stripe-Signature`; deliberately outside `get_principal`, the signature is the authentication).
- `backend/app/infrastructure/config.py` — `stripe_secret_key`, `stripe_webhook_secret`, `stripe_price_pro|studio|scale`, `stripe_price_overage`, `stripe_meter_event_name` (default `videolens_minutes`), `frontend_base_url` (where Checkout returns to; defaults to the first `ALLOWED_ORIGINS` entry).

**Flow**: checkout creates a Stripe Checkout Session in `subscription` mode with `client_reference_id=workspace_id` and `metadata.plan`, returning to `/?view=account&checkout=success|cancelled`. `checkout.session.completed` starts the subscription; `customer.subscription.created|updated` map the price id back to a plan and copy the period; `customer.subscription.deleted` (or a status in `canceled|unpaid|incomplete_expired`) drops the workspace to FREE. Unknown event types are `IGNORED` and still 200 — nothing for Stripe to retry. A bad signature is 400 `WebhookVerificationError`.

**Metering**: `RecordUsageUseCase` sends a `v2.billing.meter_events` event per metered run (`identifier=run_id` for idempotency, `value` = minutes rounded up to 0.01) when the workspace has a `stripe_customer_id`; the local `usage_events` row is written regardless.

**Stripe-side setup** (the part that cannot be code): three recurring prices, one metered overage price bound to a Meter named by `STRIPE_METER_EVENT_NAME`, a webhook endpoint for the four event types above pointed at `/api/webhooks/stripe`. See `DEPLOYMENT.md` "Paid tier setup".

**Tests**: `tests/application/test_billing.py`, `tests/infrastructure/billing/test_stripe_gateway.py` (disabled gateway, bad signature, event translation), `tests/interface/api/test_account_routes.py` (503 without Stripe, 401 anonymous).

## Changelog
- 2026-09-17 · main session · created with the Stripe adapter and billing use cases
