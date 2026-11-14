# Billing: the paid plan (Stripe)

One paid plan. It costs $12 a month (a yearly price is optional; the owner
has not settled the yearly amount) and includes 100 runs a month on the
shared Gemini key. Runs past those 100 are billed as extra runs, one at a
time, and only when a run completes. A paid account also gets the bigger
media limits (10 min / 500 MB by default) without its own key. Payment goes
through Stripe-hosted Checkout and the Stripe Customer Portal. The server
never sees a card and the frontend does not load Stripe.js. Amounts are
configured in Stripe as Prices, referenced by ID in settings, and read back
from Stripe for display. No amount is written in the code.

If any required `STRIPE_*` setting is blank, billing is off. Every account
then follows the free rules exactly as it did before billing existed, and
the `billing` capability row reads `disabled`.

History stays in the browser. Billing adds three small tables next to the
identity tables: who is subscribed, which webhooks were handled, and which
extra runs are owed. It stores no run content and no result.

## Files

| Layer | File | What |
|---|---|---|
| domain | `domain/entities.py` | `Price`, `BillingPrices`, `SubscriptionSnapshot`, `BillingAccount`, `BillingWebhookEvent`, `ExtraRunCharge` |
| domain | `domain/entitlements.py` | `Plan.PAID` (metered), `MediaTier.PAID`, `MediaTier.long_job` |
| domain | `domain/policies.py` | `subscription_grants_paid` (active/trialing plus a 3-day renewal grace), `subscription_is_live` |
| domain | `domain/ports.py` | `BillingGateway`, `BillingAccounts`, `ExtraRunLedger`; `AccountFreeRunAllowance.status/try_consume(limit=)` |
| domain | `domain/errors.py` | `Billing*Error` (each has a `code`), `WebhookSignatureError`, `ExtraRunsCapReachedError`, `SubscriptionCancelFailedError` |
| application | `application/billing.py` | `BillingPlans` (decides whether an account is paid right now), `ExtraRunBilling` (complete, void, flush) |
| application | `get_billing.py`, `start_checkout.py`, `open_billing_portal.py`, `handle_billing_webhook.py` | the four endpoints |
| application | `create_run.py` | paid admission: included runs, then an extra-run hold, the monthly safety cap, DAILY_RUN_CAP exemption |
| application | `process_run.py`, `get_run.py` | bill on a successful `set_result`; void on every other ending (including the stale-run sweep) |
| application | `get_free_runs.py`, `get_account.py`, `entitlements.py` | `plan`/`overage`, `Plan.PAID`, the paid media tier |
| application | `delete_account.py` | cancels the subscription before anything is deleted |
| infrastructure | `billing/stripe_gateway.py` | `StripeBillingGateway(settings)`: stripe-python `StripeClient`, calls run in a thread, every Stripe object reduced to a domain record |
| infrastructure | `persistence/billing_store.py` | SQL and in-memory `BillingAccounts` / `ExtraRunLedger` |
| infrastructure | `persistence/schema.py`, `migrations/versions/0004_billing.py` | the three tables |
| infrastructure | `health/probes.py` | `BillingProbe` |
| infrastructure | `config.py` | `STRIPE_*`, `PAID_*`, `BILLING_RETURN_ORIGIN`, `billing_configured`, `distributed_billing_error()` |
| interface | `api/routes.py`, `api/schemas.py`, `api/error_handlers.py` | the endpoints, DTOs, `{detail, code}` errors |
| interface | `worker/settings.py` | cron `flush_extra_runs` every 10 minutes |
| wiring | `container.py` | SQL stores with `DATABASE_URL`, in-memory without it (local only) |

## API contract

The frontend builds against these field names. Treat them as fixed.

### `GET /api/billing`

The caller must be authenticated, by a person's session or an API key. An
anonymous caller (`X-Client-ID`) gets 401, and a request with no credential
at all gets 400, the same as `/api/me`. With billing off, or with no
account store, the response is exactly `{"enabled": false}`. Otherwise:

```json
{
  "enabled": true,
  "plan": "free" | "paid",
  "status": "active" | "past_due" | "canceled" | ... | null,
  "interval": "month" | "year" | null,
  "current_period_end": "2026-12-13T00:00:00Z" | null,
  "cancel_at_period_end": false,
  "runs": {"limit": 100, "used": 12, "period": "month"},
  "prices": {
    "month": {"amount": 1200, "currency": "usd"} | null,
    "year": {"amount": 12000, "currency": "usd"} | null,
    "extra_run": {"amount": 15, "currency": "usd"} | null
  }
}
```

- `status` is Stripe's subscription status as last synced. It is `null` for
  an account that has never subscribed.
- `plan` is `"paid"` only when the status is active or trialing and the
  current period (plus 3 days of grace) has not ended. `past_due`,
  `unpaid`, `canceled` and every other status read as `"free"`.
- `runs` is the plan's own counter, and `period` says which: on the paid
  plan this UTC month's (`"month"`, limit `PAID_RUNS_PER_MONTH`); on the
  free plan today's (`"day"`, limit `FREE_RUNS_PER_ACCOUNT_DAILY`, since
  2026-11-14; it was the month's `FREE_RUNS_PER_ACCOUNT_MONTHLY` before).
- `amount` is in the currency's smallest unit (cents). A price is `null`
  when it is not configured (yearly is optional), when Stripe could not be
  read just now, or when the Price is tiered.

### `POST /api/billing/checkout`

The body is `{"interval": "month" | "year"}`. The response is `{"url":
"https://checkout.stripe.com/..."}`; send the browser there. Only a
signed-in person may call it: anonymous gets 401 and an API key gets 403.

| Status | Body | When |
|---|---|---|
| 200 | `{"url"}` | |
| 400 | `{"detail","code":"invalid_interval"}` | `year` with no yearly price configured |
| 409 | `{"detail","code":"already_subscribed"}` | the stored subscription is live (active, trialing, past_due, unpaid, incomplete or paused); open the portal instead |
| 422 | FastAPI validation | `interval` is not `month` or `year` |
| 503 | `{"detail","code":"billing_disabled"}` | billing off |
| 503 | `{"detail","code":"billing_unavailable"}` | Stripe refused or could not be reached |

Checkout returns to `{BILLING_RETURN_ORIGIN}/app?view=account&billing=success`
or `...&billing=cancel`. The page must not treat `success` as proof of
payment. The webhook makes the account paid, so poll `GET /api/billing`
after returning.

### `POST /api/billing/portal`

No body. The response is `{"url"}`, a Stripe Customer Portal session that
returns to `/app?view=account`. Only a signed-in person may call it. An
account that never started a checkout gets 404 `{"detail","code":"no_billing_account"}`.
The 503 codes are the same as for checkout.

### `POST /api/billing/webhook`

This is Stripe's endpoint. It reads the raw body and requires the
`Stripe-Signature` header. It is exempt from auth and from rate limits,
because the signature is the authentication.

| Status | When |
|---|---|
| 200 `{"received": true}` | handled, duplicate, or a type this app ignores |
| 400 `{"detail","code":"invalid_signature"}` | the signature does not verify, or the body is over 1 MB; nothing is read |
| 503 `billing_disabled` / `billing_unavailable` | billing off, or Stripe failed while re-fetching the subscription. Stripe retries it. |

The endpoint handles `checkout.session.completed`,
`customer.subscription.created`, `customer.subscription.updated`,
`customer.subscription.deleted`, `customer.subscription.paused`,
`customer.subscription.resumed`, `invoice.paid` and `invoice.payment_failed`.
It does not trust the event body for state. It re-fetches the subscription
from Stripe and stores what Stripe says now, so the order in which events
arrive never matters.

Handling is idempotent per event id. The event is marked as seen only after
the change is stored, so a failed handling is retried by Stripe and a
repeated one is a no-op. An event for an unknown customer, or for a
subscription belonging to a different customer, is acknowledged and
ignored. An old cancelled subscription never overwrites a live one. The log
gets ids only: event, customer, subscription and account.

### Changes to existing endpoints

- `GET /api/free-runs`, signed in: gains `"plan": "free" | "paid"` and
  `"overage": bool`, which is true on the paid plan, where runs past
  `limit` are billed instead of refused. On the paid plan, `limit`,
  `used` and `remaining` are the plan's included runs and `period` is
  `"month"` (every response carries `period` since 2026-11-14; free
  accounts and devices are `"day"`, `free-runs.md`). Anonymous callers
  never get `plan` or `overage`.
- `GET /api/limits` gains `"paid": {"max_duration_seconds", "max_file_size_mb"}`,
  listed whether or not billing is on.
- `GET /api/me`: `entitlement.plan` is `"paid"` (with `metered: true`) for
  a paid account, with the paid media limits.
- `POST /api/runs`: a paid account past its included runs and at
  `PAID_EXTRA_RUNS_MONTHLY_CAP` gets 402 `{"detail","code":"extra_runs_cap","limit"}`.
  This is a new code; the frontend shows "add your own key or wait for next month".
- `DELETE /api/me`: 503 `{"detail","code":"subscription_cancel_failed"}`
  when the subscription could not be cancelled. Nothing was deleted, so
  the client can retry.
- `GET /api/capabilities` gains a `billing` row (see below).

## Rules

### Paid admission (`CreateRunUseCase._admit_paid`)

1. A run with the caller's own Gemini key is admitted first, as always. It
   is never counted against the 100 and never billed.
2. A paid account takes a run from its per-account **monthly** counter in
   `account_free_runs` (key `"YYYY-MM"`, UTC calendar month), with the limit
   `PAID_RUNS_PER_MONTH`. This is unchanged by the 2026-11-14 switch of the
   free plan to a daily counter: free accounts now count on daily rows
   (`"YYYY-MM-DD"`), a different key, so a run is only ever on one of them.
   Free runs used before upgrading no longer count toward the 100 (until
   2026-11-14 they did: free and paid shared the monthly row; monthly rows
   written that way in November 2026 still count). The period lives in one
   place, `BillingPlans.PAID_RUNS_PERIOD`, and the limit in
   `PAID_RUNS_PER_MONTH`, so the owner's pending decision on paid numbers is
   a settings or one-line change.
3. Past the limit, the run is admitted and an extra-run row is held in the
   ledger. The run is never refused for running past the included runs.
4. The one refusal is the safety cap: when this month already has
   `PAID_EXTRA_RUNS_MONTHLY_CAP` extra runs (default 200; 0 turns the cap
   off), the run gets 402 `extra_runs_cap`. The cap guards against a
   runaway bill and is not a price point.
5. Paid runs are exempt from `DAILY_RUN_CAP`. The per-IP rate limit still
   applies (see Decisions).
6. Media limits: the paid tier is `PAID_MAX_*`, which default to the
   signed-in BYOK values. It applies with or without a key; with a key the
   larger of the two sets wins. Paid runs use the long job
   (`process_long_run`) and the one-long-run-per-account guard, exactly
   like signed-in BYOK runs.

`past_due`, `unpaid`, `canceled`, `incomplete` and `paused` all read as the
free plan: the free counter, the free limit, standard media limits and the
daily cap.

### Extra runs: billed once, only on success

Each ledger row moves through these states: `held`, then `due`, then
`reported`; or `held`, then `void`. Two conditional UPDATEs make every move
happen exactly once:

- `complete(run_id)` moves `held` to `due` only if the row is still held.
  `ProcessRunUseCase` calls it right after the result is stored, on the
  captions path and the full path, and then sends the Stripe meter event.
- `void(run_id)` moves `held` to `void` only if the row is still held. It
  runs on every other ending: an intake failure, the worker's `finally`, a
  run dropped before it started, and the stale-run sweep in `GetRunUseCase`.
  Of a late worker and the sweep, only one wins. A run that did not
  complete can never become due.
- The meter event's `identifier` is the run id, so Stripe drops a resend
  (`duplicate_meter_event`, which is treated as success). A crash between
  "sent" and "marked reported" therefore cannot bill twice.
- A failed report leaves the row due and never fails the run. The worker
  cron `flush_extra_runs` retries due rows every 10 minutes, and account
  deletion flushes before cancelling. Rows older than 34 days stay due and
  unbilled, because Stripe refuses meter events older than 35 days.
- A held row older than 2 days belongs to a run that can no longer finish.
  The next hold voids it.

A refunded run (a link run rejected before analysis) is a failed run, so
it is voided and never billed.

### Subscription state

`billing_accounts` is a cache of Stripe and never the source of truth. The
webhook overwrites it from a fresh read. Checkout checks it for a live
subscription (409). Admission and the views read it through
`BillingPlans.paid_account`.

## Decisions

### Yearly plus overage: one meter, flexible billing mode

Stripe requires every price on a classic subscription to share one billing
interval. A yearly base price and a monthly metered extra-run price would
break that rule. The options:

1. **Flexible billing mode (chosen).** `billing_mode=flexible` (API
   2025-06-30.basil and later; mixed intervals from 2025-07-30.basil)
   allows prices with different intervals on one subscription. Checkout
   sends `subscription_data.billing_mode.type=flexible` for every plan, so
   a yearly subscription is [yearly base, monthly metered] and extra runs
   are invoiced every month in arrears, the same as on the monthly plan.
   stripe-python 17 pins API 2026-10-28.endive, which is well past both
   versions. **Not verified**: whether hosted Checkout accepts mixed
   intervals in your account. Confirm it in test mode (setup step 6).
2. **Fallback: a yearly metered price.** Set `STRIPE_PRICE_EXTRA_RUN_YEARLY`
   to a yearly metered price on the same meter. Yearly subscriptions then
   carry [yearly base, yearly metered], which is a single interval and
   works on any API version. The trade-off: a year of extra runs is billed
   once, at the end of the year, which is a large surprise invoice. The
   monthly cap still bounds it.
3. Rejected: a second subscription for overage (two invoices, and the
   portal shows two plans), or invoice items created by the server (the
   server would need to keep a monthly tally).

A Billing Meter, rather than legacy usage records, is used because meters
are Stripe's current usage API, and the meter event `identifier` gives
idempotency per run for free.

### DAILY_RUN_CAP: paid runs are exempt

`DAILY_RUN_CAP` bounds free spend on the shared key per day. Paid runs are
paid for: included runs by the subscription, extra runs per run. Letting
free traffic use up the cap and then refuse a paying customer with 503 is
the wrong way round. Paid runs therefore skip it. The per-IP rate limit
(`RATE_LIMIT_PER_HOUR`) still applies to everyone, and the extra-run cap
bounds a single account.

### Deletion cancels first, with no refund

`DELETE /api/me` cancels the Stripe subscription before deleting anything:

1. If it cannot read the billing row, it refuses.
2. With no row, or no subscription, deletion proceeds as before.
3. With billing off but a live subscription on file (the keys were
   removed), it refuses, because that subscription cannot be cancelled.
4. Otherwise it reports due extra runs first, so the final invoice carries
   them, then cancels at once (`invoice_now=true, prorate=false`: no
   credit for the unused part of the period).
5. A cancel failure gives 503 `subscription_cancel_failed` and nothing is
   deleted.

The Stripe Customer record, with its email, invoices and payment method,
stays in Stripe after deletion. The app cannot delete it, because Stripe
keeps invoices for tax records. The owner deletes it from the dashboard if
asked.

## Settings

| Variable | Default | |
|---|---|---|
| `STRIPE_SECRET_KEY` | blank | `sk_test_...` (test mode) or a restricted key. Required. |
| `STRIPE_WEBHOOK_SECRET` | blank | `whsec_...` from the webhook endpoint (or from `stripe listen`). Required. |
| `STRIPE_PRICE_MONTHLY` | blank | monthly licensed Price ID. Required. |
| `STRIPE_PRICE_YEARLY` | blank | yearly licensed Price ID. Optional; blank means checkout refuses `year` with 400. |
| `STRIPE_PRICE_EXTRA_RUN` | blank | monthly metered Price ID on the meter. Required. |
| `STRIPE_PRICE_EXTRA_RUN_YEARLY` | blank | optional yearly metered price for yearly plans (fallback 2 above) |
| `STRIPE_METER_EVENT_NAME` | `videolens_extra_run` | the meter's event name. Required (it has a default). |
| `BILLING_RETURN_ORIGIN` | blank | where Checkout and the portal return. Blank means the first non-`*` `ALLOWED_ORIGINS` entry, else `http://localhost:3005`. |
| `PAID_RUNS_PER_MONTH` | 100 | included runs per UTC month |
| `PAID_EXTRA_RUNS_MONTHLY_CAP` | 200 | extra runs per account per month before 402 `extra_runs_cap`; 0 turns the cap off |
| `PAID_MAX_DURATION_SECONDS` | 0 | 0 or less means `SIGNED_IN_BYOK_MAX_DURATION_SECONDS` |
| `PAID_MAX_FILE_SIZE_MB` | 0 | 0 or less means `SIGNED_IN_BYOK_MAX_FILE_SIZE_MB` |

In distributed mode (`REDIS_URL` set), billing configured without
`DATABASE_URL` refuses to start (`Settings.distributed_billing_error`).
Locally, without a database, the in-memory stores let you try the whole
flow against Stripe test mode. They are lost on restart.

## Capability row

The `billing` row is `disabled` when Stripe is not configured or there is
no account store (it is not probed). It is `ok` when the plan's Price
objects can be read (`probed=true`, read through the gateway's one-hour
cache; a read never charges anything). It is `degraded` when the monthly
price cannot be read. `log_detail` says whether the key is in test or live
mode.

## Owner setup (Stripe test mode)

Everything here is done in the Stripe dashboard with **Test mode** on.
Nothing in this repository creates Stripe objects.

1. **Product.** Create a product named "VideoLens Paid".
2. **Prices on it.**
   - Monthly: recurring, licensed, $12.00 every month. Copy the ID into
     `STRIPE_PRICE_MONTHLY`.
   - Yearly (optional; amount pending, about $120): recurring, licensed,
     every year. Copy the ID into `STRIPE_PRICE_YEARLY`.
3. **Meter.** Billing, then Meters, then Create:
   - event name `videolens_extra_run` (or set `STRIPE_METER_EVENT_NAME`)
   - aggregation **Sum** of the payload key `value`
   - customer mapping from the payload key `stripe_customer_id`
4. **Extra-run price.** On the same product, add a recurring **usage-based**
   price on that meter, billed monthly, at your per-run amount. Copy the ID
   into `STRIPE_PRICE_EXTRA_RUN`. Optionally add a yearly one for the
   fallback and copy it into `STRIPE_PRICE_EXTRA_RUN_YEARLY`.
5. **Customer Portal.** Settings, then Billing, then Customer portal:
   - allow cancelling (at period end is fine; deletion cancels immediately
     through the API)
   - allow updating the payment method and viewing invoices
   - leave "switch plans" off, because the portal cannot update usage-based
     subscriptions.
6. **Check mixed intervals.** With the keys set locally, run one yearly
   checkout with the test card `4242 4242 4242 4242`. If Checkout rejects
   the line items, set `STRIPE_PRICE_EXTRA_RUN_YEARLY` (fallback 2).
7. **Webhook.**
   - Locally, run `stripe listen --forward-to localhost:8000/api/billing/webhook`
     and put the `whsec_...` it prints into `STRIPE_WEBHOOK_SECRET`. Trigger
     events with `stripe trigger customer.subscription.updated`. A trigger
     for a customer this app did not create is acknowledged and ignored.
   - Deployed, use Developers, then Webhooks, then Add endpoint, with
     `https://<api>/api/billing/webhook` and the eight events listed above.
     Copy its signing secret.
8. **Secret key.** Use `sk_test_...` from Developers, then API keys, or a
   restricted key with write access to Customers, Checkout Sessions,
   Customer portal, Subscriptions, Billing meter events, and read access to
   Prices. Put it in the platform's variables only, never in the repo.

## Deploy order

1. Apply migration `0004_billing` (`alembic upgrade head`) to the
   database. With billing off nothing reads these tables, so applying it
   early is harmless. **Not applied to any remote database by this
   change.**
2. Deploy the worker and API code with the `STRIPE_*` variables still
   blank. Behaviour is unchanged.
3. Create the Stripe objects (above), then set the variables on both the
   API and the worker (the worker reports extra runs), then add the webhook
   endpoint.
4. Check that `GET /api/capabilities` shows `billing: ok`, then do one test
   checkout.

## Known issues

- The extra-run cap is a check followed by a hold, not one atomic step. Two
  runs started at the same instant at the cap can both pass, overshooting
  by the number of concurrent intakes. This is acceptable for a safety net.
- Android: Checkout and the portal return to the web origin
  (`BILLING_RETURN_ORIGIN`), not into the installed APK. The app needs to
  open them in the system browser and refetch `GET /api/billing` on resume.
  This is frontend work.
- Mixed-interval Checkout is unverified (setup step 6).
- A local API without `REDIS_URL` has no worker cron. Due extra runs whose
  report failed are retried only by account deletion, or are lost on
  restart (in-memory). This affects local testing only.
- The Stripe Customer record outlives account deletion (see Decisions).
- `incomplete` (a first payment that needs authentication) blocks a new
  checkout with 409 until Stripe expires it (about 23 hours). The portal
  is the way out.

## Tests

- `tests/application/test_billing.py`: checkout, portal and view; webhook
  signature, idempotency, transitions and ordering; paid admission within
  and over the limit; the cap; BYOK not counted; past_due treated as free;
  billed once and only on success (including retries, failures and the
  stale sweep); deletion cancels, or refuses on a Stripe failure;
  billing-off parity.
- `tests/infrastructure/persistence/test_billing_store.py`: the SQL
  (SQLite) and in-memory stores share one suite; deletion cascade;
  Alembic 0004 up and down; the Postgres branch with Alembic mocked.
- `tests/infrastructure/billing/test_stripe_gateway.py`: the Stripe calls
  against a mocked `StripeClient`, and real signature verification with a
  locally signed payload.
- `tests/interface/api/test_billing_routes.py`: the exact JSON contract,
  status codes, billing off, `free-runs` fields, and deletion.
- `tests/infrastructure/health/test_billing_probe.py`: the capability row
  and the settings.

## Changelog
- 2026-11-13 · backend agent · created: paid plan through Stripe-hosted Checkout and Portal; `GET /api/billing`, `POST /api/billing/checkout|portal|webhook`; paid admission on the account counter (`PAID_RUNS_PER_MONTH`), extra runs through a held/due/reported ledger and a Billing Meter (identifier = run id), billed only on success; paid media tier; DAILY_RUN_CAP exemption; `extra_runs_cap` 402; deletion cancels the subscription first; migration 0004; `billing` capability row
- 2026-11-14 · backend agent · the paid counter is still monthly (100/month, metered overage unchanged); the free plan moved to daily rows, so free and paid no longer share a row; `runs.period` on `GET /api/billing`; paid period in `BillingPlans.PAID_RUNS_PERIOD`
