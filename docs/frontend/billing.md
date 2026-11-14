# Billing (client half)

The paid plan, owner's "Level 3, one paid plan" (2026-11-13): $12 a month (or
a yearly price) for 100 runs a month on our Gemini key, videos up to 10
minutes / 500 MB without a key of your own, extra runs past 100 billed per
run. BYOK runs never count. History stays in the browser. The server half
(Stripe, webhooks, the per-account run count) is the backend's doc; this one
covers what the app shows and how it gets to Stripe.

No Stripe.js, no card fields, no new dependency. Checkout and the Customer
Portal are Stripe-hosted pages reached by a top-level redirect.

**Billing off looks exactly like before.** Nothing is fetched and nothing is
drawn unless the server's `billing` capability is `ok` *and* someone is
signed in (the same gate as the Account tab) *and* `GET /api/billing` answers
`{"enabled": true, ...}`. Any failure hides the Plan group.

## Contract used

- `GET /api/billing` (bearer required; anonymous 401). Off: `{"enabled":
  false}`. On: `{"enabled": true, "plan": "free"|"paid", "status",
  "interval": "month"|"year"|null, "current_period_end", "cancel_at_period_end",
  "runs": {"limit", "used"}, "prices": {"month", "year", "extra_run"}}`, each
  price `{"amount", "currency"}` (minor units) or null.
- `POST /api/billing/checkout` `{"interval"}` → `{"url"}`; 409
  `already_subscribed`.
- `POST /api/billing/portal` → `{"url"}`; 404 `no_billing_account`.
- Both return to `/app?view=account&billing=success|cancel`.
- `GET /api/free-runs` gains `plan` and `overage`; `GET /api/limits` gains an
  optional `paid` tier; the capabilities report gains a `billing` row.

## Layers

| Layer | File | What |
|---|---|---|
| domain | `domain/entities.ts` | `BillingPlan`, `BillingInterval`, `BillingPrice(s)`, `BillingStatus`, `BillingDetails` (the enabled variant); `FreeRunsStatus.plan/overage`; `MediaLimitsTable.paid` |
| domain | `domain/ports.ts` | `BillingGateway` (`fetchBilling`, `startCheckout`, `openPortal`) |
| infrastructure | `infrastructure/billingGateway.ts` | `FetchBillingGateway` over the shared `ApiClient` (bearer rides along). Normalises: only a literal `enabled: true` turns billing on; unreadable run counts throw; a price needs a count and a 3-letter currency or it is null; the redirect URL must be `https:` |
| infrastructure | `infrastructure/container.ts` | `billingGateway` |
| application | `application/useBilling.ts` | Module store (like `useFreeRuns`) with an owner epoch. `useBilling(userId, enabled)` (called once, HomeScreen) and `useBillingActions()` (Plan group) |
| application | `application/useMainTab.ts` | `takeSearchParam(name)`: read a query param and strip it with `replaceState`, keeping Next's history state |
| components | `components/panels/AccountPanel.tsx` | `PlanGroup`, the checkout-return notice, the paid identity line |
| components | `components/FreeRunsBanner.tsx` | Paid strip copy; the "or upgrade" link on a spent free account |
| components | `components/format.ts` | `formatPrice` (Intl, the currency's own exponent, whole amounts without decimals), `formatLongDay` |

## Account: the Plan group

A group labelled "Plan" above "Your account" (option A grouped list, one
padded card, no pricing table: there is one plan).

- **Free.** "Free", then (2026-11-14) "The paid plan: videos up to 10
  minutes without your own key, and runs past the daily limit." (without a
  `paid` tier in `/api/limits`: "The paid plan: runs past the daily limit,
  without your own key."), plus, when the extra-run price is known,
  " Beyond its 100 included runs a month, each run is $0.xx.". Until
  2026-11-14 it led with "100 runs a month on our key"; with the free account
  at 10 a day (up to ~300 a month) that read as fewer runs for money, so the
  pitch names what the plan adds and makes no run-count comparison. **The
  paid offer itself needs an owner rethink** (100 a month is below a free
  account's daily allowance over a month), then "Upgrade — $12/month" (primary) and "Yearly — $X/year"
  (secondary). A null price hides its button; no prices, no buttons. Note
  under the card: "Billed through Stripe. Cancel anytime. Runs with your own
  Gemini key never count."
- **Paid.** "Paid · Monthly|Yearly", "Renews <date>" or "Ends <date>" when
  `cancel_at_period_end`, "Payment failed — update your card in Manage
  billing." when `status` is `past_due` or `unpaid` (and Manage billing turns
  primary), "N of L used this month." and "Extra runs are $0.xx each.", then
  "Manage billing".
- **Actions.** A press asks the server for the URL (label "Opening…",
  `aria-disabled` on both buttons), then `window.location.assign(url)`.
  `already_subscribed` → "You are already on the paid plan." + re-read;
  `no_billing_account` → a sentence + re-read; anything else through
  `classifyGatewayError`. A `pageshow` with `persisted` (back button from
  Stripe restoring the page from bfcache) clears "Opening…" and re-reads.
- **Identity line.** Paid: "Runs left this month: N of L" (no "Free").

## Returning from Checkout

`?billing=` is read once per load (`takeCheckoutReturn`) and stripped, so a
reload does not repeat the notice. The notice sits under the Account header
in an always-mounted `role="status"` slot (empty, it takes no space):

- `cancel` → "Checkout cancelled. Nothing was charged." (quiet tone).
- `success` → "Confirming payment…" while the plan is re-read at 0, 1.5, 4,
  8, 13 and 20 s (the webhook can land after the redirect); it stops at the
  first `paid` and becomes "You’re on the paid plan.", else "We have not seen
  your payment yet. If you completed checkout, it will show here shortly."
  Either way the free-runs read is revalidated so the strip and upload limits
  follow.
- Signed out on return (paid in a browser where the app's session is not):
  "Checkout finished. Sign in with the email you paid with to see your plan."

The plan is also re-read on `visibilitychange` → visible and on the native
app's resume, throttled to once per 1.5 s.

## Free-runs strip and limits

- Paid, not exhausted: "**N of L runs left this month.**" with no pill.
- Paid, past the allowance with `overage`: "**You have used this month's L
  runs.** Extra runs are billed at $0.xx each." Not blocked.
- Free account spent, billing on: the add-key sentence gains ", or upgrade."
  linking to Account.
- `useMediaLimits(signedIn, paid)`: `paid` tier when the plan is paid and the
  server reported one, else `signed_in_byok` with a key, else `standard`.
  `paid` comes from the billing read or the free-runs `plan`, whichever knows.

## The installed app (decision)

No Browser plugin. In the Capacitor WebView, `location.assign` to a host that
is not the app's own goes through `BridgeWebViewClient.shouldOverrideUrlLoading`
→ `bridge.launchIntent`, which opens it with `ACTION_VIEW` in the system
browser and leaves the WebView where it was: the same path `target="_blank"`
links already take (`UpdatePrompt`). So the same code works on web and
Android. After the hand-off the panel says "Opened in your browser. Come back
here when you’re done." and the plan is re-read on resume. The Stripe return
URL then lands in the browser, not the app: there the user sees the web app
(signed out unless they also signed in there, hence the signed-out notice).
Paying in the browser is deliberate: Stripe's pages need a real browser, and
an in-app WebView checkout is what store policies look hardest at.

## CSP (finding: no change)

`security/csp.mjs` needs nothing. `connect-src` governs `fetch`, and every
billing fetch goes to the API origin, which is already allowed. Moving to
`checkout.stripe.com` / `billing.stripe.com` is a top-level navigation, which
CSP does not govern (`navigate-to` never shipped). `form-action 'self'` does
not apply: no form posts to Stripe. `Permissions-Policy: payment=()` only
restricts the Payment Request API in our own documents, not Stripe's page.
No inline script was added, so the hashes are unchanged.

## Legal (drafts)

Terms gain a "Paid plan" section (auto-renewing monthly/yearly until
cancelled; cancel in Manage billing and keep access to the end of the paid
period; extra runs billed per run at the checkout price; BYOK runs do not
count; no refunds for partial periods except where the law requires; price
changes announced before renewal). Privacy gains "Payments" (Stripe processes
payments; we never see or store the card number; we keep the Stripe customer
and subscription IDs, plan status and renewal date, and a monthly run count),
and "Third-party services" names Stripe. **Both are drafts for the owner's
legal review.** The media-terms key moved to `videolens-media-terms-v3`
(v1 and v2 retired) so everyone re-accepts once.

## Error codes (follow-up, 2026-11-13)

| Where | Response | What the app says |
|---|---|---|
| `POST /api/runs` | 402 `extra_runs_cap` (`limit`, default 200) | "You’ve reached this month’s limit of N extra runs. Runs reset next month." (`createRunFailureMessage` in `runsGateway.ts`; shown as the run's error line; no upgrade offer, the account is already paid; not treated as `free_runs_used`) |
| `DELETE /api/me` | 503 `subscription_cancel_failed` | Deletion problem `subscription` in `useAccount.ts`: "We couldn’t cancel your subscription, so your account was not deleted. Your account and subscription are unchanged. Try again in a moment." Checked before the generic 503 ("not available"); the form stays usable |
| checkout / portal | 400 `invalid_interval`, 503 `billing_disabled` / `billing_unavailable` | "Billing is unavailable right now. Try again later." (`useBillingActions`) |

Deleting an account cancels any subscription immediately (no refund for the
rest of the period); billing rows are deleted, Stripe keeps its customer
record for invoices and tax. Terms "Paid plan" and Privacy "Payments" say so
(still drafts).

## Known limits

- The pitch's "100 runs" is a constant (`PAID_RUNS_PER_MONTH`) until someone
  is paid, because the free-plan body's `runs.limit` is the free allowance.
- A user who pays in the browser and never signs in there sees the plan only
  after the app next reads billing (resume or tab visible).

## Changelog

- 2026-11-13 · frontend agent · created: billing gateway + `useBilling`, Account Plan group, checkout-return notice, paid strip copy and "or upgrade" link, paid upload tier, Terms "Paid plan" and Privacy "Payments" drafts, terms key v3, CSP reviewed (no change)
- 2026-11-13 · frontend agent · handled 402 `extra_runs_cap`, 503 `subscription_cancel_failed` on account deletion, and 400 `invalid_interval` / 503 `billing_disabled`/`billing_unavailable` on checkout and portal; Terms and Privacy say deleting the account cancels the subscription immediately
- 2026-11-14 · frontend agent · free-plan pitch no longer leads with "100 runs a month" (the free account is now 10 a day): "videos up to 10 minutes without your own key, and runs past the daily limit", included runs and extra-run price as a trailing clause; offer flagged for an owner rethink
