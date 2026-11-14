# Billing (client half)

The paid plan, owner's "Level 3, one paid plan" (2026-11-13): $12 a month (or
a yearly price) for **30 runs a day** (UTC; 100 a month until 2026-11-14) on
our Gemini key, videos up to 10 minutes / 500 MB without a key of your own,
extra runs past the 30 billed per run with a hard cap of **200 extra runs a
calendar month**. Never described as unlimited. BYOK runs never count. History stays in the browser. The server half
(Stripe, webhooks, the per-account run count) is the backend's doc; this one
covers what the app shows and how it gets to Stripe.

No Stripe.js, no card fields, no new dependency. Checkout and the Customer
Portal are Stripe-hosted pages reached by a top-level redirect.

**Billing off looks exactly like before.** Nothing is fetched and nothing is
drawn unless the server's `billing` capability is `ok` *and* someone is
signed in (the same gate as the Account tab) *and* `GET /api/billing` answers
`{"enabled": true, ...}`. A failed request retains the reserved Upgrade /
Billing space with "Billing unavailable."; disabled billing still draws
nothing. The Plan and usage card remains independent of billing.

## Contract used

- `GET /api/billing` (bearer required; anonymous 401). Off: `{"enabled":
  false}`. On: `{"enabled": true, "plan": "free"|"paid", "status",
  "interval": "month"|"year"|null, "current_period_end", "cancel_at_period_end",
  "runs": {"limit", "used", "period"}, "extra_runs", "prices": {"month", "year", "extra_run"}}`, each
  price `{"amount", "currency"}` (minor units) or null. `runs.period`
  (2026-11-14) is `day` on both plans; missing reads as `day`
  (`BillingDetails.runs.period`). `extra_runs` (2026-11-14, backend commit
  12d30d0) is `{"used", "limit", "period": "month", "resets_at"}` on a paid
  account and null on a free one; `limit` is null when the monthly cap is
  off. Read into `BillingDetails.extraRuns` (`BillingExtraRuns`): only for
  `plan: "paid"`, and a missing, null or unreadable field (unreadable count,
  or a limit that is neither a count nor null) becomes null, so an older
  backend leaves the Billing card exactly as it was.
- `POST /api/billing/checkout` `{"interval"}` → `{"url"}`; 409
  `already_subscribed`.
- `POST /api/billing/portal` → `{"url"}`; 404 `no_billing_account`.
- Both return to `/app?view=account&billing=success|cancel`.
- `GET /api/free-runs` gains `plan` and `overage`; `GET /api/limits` gains an
  optional `paid` tier; the capabilities report gains a `billing` row.

## Layers

| Layer | File | What |
|---|---|---|
| domain | `domain/entities.ts` | `BillingPlan`, `BillingInterval`, `BillingPrice(s)`, `BillingExtraRuns`, `BillingStatus`, `BillingDetails` (the enabled variant); `FreeRunsStatus.plan/overage`; `MediaLimitsTable.paid` |
| domain | `domain/ports.ts` | `BillingGateway` (`fetchBilling`, `startCheckout`, `openPortal`) |
| infrastructure | `infrastructure/billingGateway.ts` | `FetchBillingGateway` over the shared `ApiClient` (bearer rides along). Normalises: only a literal `enabled: true` turns billing on; unreadable run counts throw; a price needs a count and a 3-letter currency or it is null; the redirect URL must be `https:` |
| infrastructure | `infrastructure/container.ts` | `billingGateway` |
| application | `application/useBilling.ts` | Module store (like `useFreeRuns`) with an owner epoch. `useBilling(userId, enabled)` (called once, HomeScreen) and `useBillingActions()` (Plan group) |
| application | `application/useMainTab.ts` | `takeSearchParam(name)`: read a query param and strip it with `replaceState`, keeping Next's history state |
| components | `components/panels/AccountPanel.tsx` | `UpgradeGroup`, `BillingGroup` (and their reserved stand-in), the checkout-return notice; `PlanUsageGroup` reads the plan name |
| components | `components/FreeRunsBanner.tsx` | Paid strip copy; the "or upgrade" link on a spent free account |
| components | `components/format.ts` | `formatPrice` (Intl, the currency's own exponent, whole amounts without decimals), `formatLongDay` |

## Account: Plan and usage, then Upgrade or Billing (2026-11-14)

The single "Plan" group is now three (`AccountPanel.tsx`). The earlier pitch
sentence ("30 runs a day instead of 10, videos up to 10 minutes, and no
Gemini key needed") is gone: it read as if a free account needed a key.

- **Plan and usage** (`PlanUsageGroup`) is drawn for every signed-in
  account and does **not** depend on billing; it is documented in
  `auth-sign-in.md`. With billing on it takes the plan name from this read
  as well as from `/api/free-runs`.
- **Upgrade** (`UpgradeGroup`; free account, billing on). A two-column table
  (real `<table>`, sr-only caption "Your free account compared with the paid
  plan"), columns "Your free account" and "Paid plan":
  - "Runs a day": `runs.limit` (10) against `PAID_RUNS_PER_DAY` (30).
  - "Video length" (only when `/api/limits` reports a `paid` tier): "Up to 3
    minutes" + "or 10 with your own Gemini key" against "Up to 10 minutes" +
    "with no Gemini key". "No key needed" is never offered as a paid benefit
    on its own: a free account's runs need no key either. The one
    paid-only point is the longer video without a key.
  - Then the price ("$12 a month"; the yearly price when there is no monthly
    one), one primary button "Upgrade to paid" (monthly checkout, yearly when
    that is the only price), and, when both prices exist, a quiet text
    control "Or pay $120 a year". No price, no button.
  - On its own line: "Past the 30, extra runs are $0.15 each, up to 200 a
    month." (no extra-run price: "…are billed per run, up to 200 a month.").
    Never "unlimited".
  - Note under the card: "Billed through Stripe. Cancel anytime. Runs with
    your own Gemini key never count."
- **Billing** (`BillingGroup`; paid). Rows "Price" → "$12 a month" / "$120 a
  year" ("Billed monthly|yearly" if that price is null) and "Renews" /
  "Ends" (`cancel_at_period_end`) → the date; "Payment failed. Update your
  card in Manage billing." when `status` is `past_due` or `unpaid` (Manage
  billing turns primary); "Extra runs this month" → "37 of 200" (the
  server's `extra_runs.used` and `limit`; just "37" when the limit is null,
  never an invented cap; no row when the field is absent or null); the
  extra-run terms line, unchanged; "Manage billing". Runs left today is in
  the Plan and usage card directly above and is not repeated.
- **Reserved height.** `useBilling().pending` is true from the moment an
  owner is set until the read answers (`Snapshot.settled`, success or
  failure). Meanwhile the panel lays out the group it expects (Upgrade, or
  Billing if `/api/free-runs` already said `paid`) with stand-in values,
  `visibility: hidden`, `aria-hidden`, `inert`, so the groups below do not
  drop when the real one lands. The stand-in's card frame is shown (its
  contents stay hidden), and static muted placeholder lines are painted
  inside that frame by an absolutely positioned overlay, so the dimensions
  never change. On failure the same framed card says "Billing unavailable.";
  a later successful read recovers it. (Codex's first pass drew the lines
  over an invisible group, which read as a blank hole; reviewed 2026-11-14.)
  The stand-in is the Billing card when `/api/free-runs`, `/api/billing` or
  the session's `/api/me` entitlement already says `paid`.
  `useBilling().failed` distinguishes failure from disabled billing; a
  failed refresh keeps the last-known data for sizing and entitlements.
  With billing off nothing is reserved. The
  paid stand-in carries an extra-runs row (0 of 200), so the row is reserved
  too; an older backend without the field leaves the row invisible and
  unannounced, preserving its space when the card lands.
- **Actions.** A press asks the server for the URL (label "Opening…",
  `aria-disabled` on every control), then `window.location.assign(url)`.
  `already_subscribed` → "You are already on the paid plan." + re-read;
  `no_billing_account` → a sentence + re-read; anything else through
  `classifyGatewayError`. A `pageshow` with `persisted` (back button from
  Stripe restoring the page from bfcache) clears "Opening…" and re-reads.

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

- Paid, not exhausted: "**N of 30 runs left today.**" with no pill.
- Paid, past the allowance with `overage`: "**You have used today's 30
  runs.** Extra runs are billed at $0.xx each, up to 200 a month." Not
  blocked.
- Free account spent, billing on: the add-key sentence gains ", or upgrade
  for 30 a day." ("upgrade" links to Account).
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
and subscription IDs, plan status and renewal date, a daily run count and,
since 2026-11-14, a monthly extra-run count),
and "Third-party services" names Stripe. **Both are drafts for the owner's
legal review.** The media-terms key moved to `videolens-media-terms-v3`
(v1 and v2 retired) so everyone re-accepts once.

## Error codes (follow-up, 2026-11-13)

| Where | Response | What the app says |
|---|---|---|
| `POST /api/runs` | 402 `extra_runs_cap` (`limit`, default 200) | "You’ve reached this month’s limit of N extra runs. Your included runs come back tomorrow." (2026-11-14; was "Runs reset next month.") (`createRunFailureMessage` in `runsGateway.ts`; shown as the run's error line; no upgrade offer, the account is already paid; not treated as `free_runs_used`) |
| `DELETE /api/me` | 503 `subscription_cancel_failed` | Deletion problem `subscription` in `useAccount.ts`: "We couldn’t cancel your subscription, so your account was not deleted. Your account and subscription are unchanged. Try again in a moment." Checked before the generic 503 ("not available"); the form stays usable |
| checkout / portal | 400 `invalid_interval`, 503 `billing_disabled` / `billing_unavailable` | "Billing is unavailable right now. Try again later." (`useBillingActions`) |

Deleting an account cancels any subscription immediately (no refund for the
rest of the period); billing rows are deleted, Stripe keeps its customer
record for invoices and tax. Terms "Paid plan" and Privacy "Payments" say so
(still drafts).

## Known limits

- The comparison's "30 a day" and the terms line's "200 a month" are constants (`PAID_RUNS_PER_DAY`,
  `PAID_EXTRA_RUNS_PER_MONTH`), because the free-plan body's `runs.limit` is
  the free allowance and the free body carries no extra-run cap
  (`extra_runs` is null there). The paid card's "Extra runs this month" row
  uses the server's own `extra_runs.limit`; the terms sentence beside it
  still uses the constant. If the server's cap setting changes, change the
  constant too.
- `extra_runs.used` counts runs still in flight past the included ones
  (backend `held` rows), so it can be one or two ahead of what Stripe has
  billed. `resets_at` is read but not shown.
- A user who pays in the browser and never signs in there sees the plan only
  after the app next reads billing (resume or tab visible).

## Saved history and the plan (2026-11-14)

The Upgrade comparison has a third row group, History: "Last 20 in this
browser" against "Saved to your account, on every device". After a plan
ends, saved runs are kept until `expires_at`; History shows a quiet notice
with the date and the Account page's History row says "Saved to your account
until <date>". Restoring a held account calls `refreshBilling()`; it comes
back on the free plan. See `saved-history.md`.

## Changelog

- 2026-11-14 · Codex · added static billing loading lines and an unavailable overlay within the existing reservation, retained the paid extra-runs row's space for older responses, and strengthened Account usage emphasis without changing the upgrade comparison

- 2026-11-13 · frontend agent · created: billing gateway + `useBilling`, Account Plan group, checkout-return notice, paid strip copy and "or upgrade" link, paid upload tier, Terms "Paid plan" and Privacy "Payments" drafts, terms key v3, CSP reviewed (no change)
- 2026-11-13 · frontend agent · handled 402 `extra_runs_cap`, 503 `subscription_cancel_failed` on account deletion, and 400 `invalid_interval` / 503 `billing_disabled`/`billing_unavailable` on checkout and portal; Terms and Privacy say deleting the account cancels the subscription immediately
- 2026-11-14 · frontend agent · free-plan pitch no longer leads with "100 runs a month" (the free account is now 10 a day): "videos up to 10 minutes without your own key, and runs past the daily limit", included runs and extra-run price as a trailing clause; offer flagged for an owner rethink
- 2026-11-14 · frontend agent · paid plan is 30 runs a day: pitch "The paid plan: 30 runs a day instead of 10, videos up to 10 minutes, and no Gemini key needed. Past the 30, extra runs are $X each, up to 200 a month."; paid card "N of L used today." and "Extra runs are $X each, up to 200 a month."; identity "Runs left today"; `runs.period` read (missing = day); `PAID_RUNS_PER_MONTH` removed; Terms and Privacy follow
- 2026-11-14 · frontend agent · Account refinement: the Plan group is split into Plan and usage (always, see auth-sign-in.md), Upgrade (two-column comparison, price, one "Upgrade to paid" action, yearly as a quiet link, extra-run terms on their own line) and Billing (price, renews/ends, terms, Manage billing); pitch sentence removed; `useBilling().pending` + an inert stand-in reserve the group's height; extra runs used this month not shown (not in the API)
- 2026-11-14 · frontend agent · paid Billing card shows "Extra runs this month" ("N of L", or "N" when the cap is off) from the new `extra_runs` field (`BillingExtraRuns`, normalised to null when absent/unreadable or on a free plan); the reserved paid stand-in includes the row; terms sentence unchanged
- 2026-11-14 · frontend agent · loading / failed billing now shows the reserved card's frame with the static lines or "Billing unavailable." inside it (was a blank hole); `/api/me`'s plan also picks the paid stand-in; extra-runs row and reserved heights re-verified in the browser
2026-11-14 · frontend agent · Upgrade comparison gains a History row (last 20 in this browser vs saved to your account, on every device); restoring a held account re-reads the plan (`refreshBilling`); the plan-ended window for saved runs is shown on History and the Account History row (see saved-history.md)
