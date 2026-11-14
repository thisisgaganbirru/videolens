# Free runs (frontend)

Anonymous devices get a few free runs per UTC day. Without a saved Gemini key,
the intake shows how many are left, and once they are spent it blocks
submitting until a key is saved. With a key saved there is no banner and no
limit. The server half (signing, counters, the IP backstop, how easy it is to
bypass) is `docs/backend/free-runs.md`.

**Files**
- `frontend/domain/entities.ts`: `FreeRunsStatus`.
- `frontend/domain/errors.ts`: `ApiError` now carries `code`, `limit` and `used` from the error body, so callers branch on `code` and never on message text.
- `frontend/domain/ports.ts`: `FreeRunsGateway`, `DeviceTokenStore`, and `ApiKeyStore.subscribe`.
- `frontend/infrastructure/freeRunsGateway.ts`: `FetchFreeRunsGateway` (`GET /api/free-runs`). Normalises the body, and writes back any token that differs from the stored one.
- `frontend/infrastructure/deviceTokenStore.ts`: `LocalStorageDeviceTokenStore`, key `videolens-device-token`. Every access is wrapped in try/catch.
- `frontend/infrastructure/clientId.ts`: `getClientId()`, moved out of `runsGateway.ts` now that two adapters send `X-Client-ID`.
- `frontend/infrastructure/runsGateway.ts`: `createRun` sends `X-Device-Token`, and passes the body's `code`/`limit`/`used` into the `ApiError`.
- `frontend/infrastructure/apiKeyStore.ts`: `subscribe()` covers same-tab writes and other tabs' `storage` events.
- `frontend/application/useFreeRuns.ts`: a module-level store plus `useFreeRuns()`, `refreshFreeRuns()`, `markFreeRunsUsed()` and `noteRunAccepted()`.
- `frontend/application/useAnalysisRun.ts`: the 401 retry and the 402 handling in `submit`.
- `frontend/components/FreeRunsBanner.tsx`: the banner.
- `frontend/components/HomeScreen.tsx`: the always-present `.free-runs-slot` (`role="status"`) above the eyebrow, and `blocked` passed to `UploadForm`.
- `frontend/components/UploadForm.tsx`: the `blocked` prop.
- `frontend/app/globals.css`: `.free-runs*`, plus a short-desktop tightening.
- `frontend/components/panels/ApiKeyPanel.tsx`: the lede.
- `frontend/app/privacy/page.tsx`: one sentence about the device token.

## Contract used

- `GET /api/free-runs` (sends `X-Device-Token` when stored, plus `X-Client-ID`) returns `{device_token, limit, used, remaining, resets_at, enabled}`.
- `POST /api/runs` sends `X-Device-Token` alongside `X-Gemini-Api-Key`, and both go on run creation only.
  - 401 `code: "device_token_invalid"`: `refreshFreeRuns()` (which stores the new token), then the same `createRun` again, **once**. A second refusal is shown like any other error.
  - 402 `code: "free_runs_used"`: `markFreeRunsUsed(limit, used)` puts up the limit state straight away, even if the cached count still said runs were left, then confirms with a fresh read. No intake error line, because the banner says it. If the 402 came from "Try again" on the failed view, the screen returns to idle so the banner is visible. With a key saved, the banner is hidden, so the server's sentence is shown instead (unreachable in practice).

## When the status is read

- On mount of the shell (`HomeScreen`, which a tab switch never unmounts), if no key is saved.
- When the saved key is removed (`ApiKeyStore.subscribe`).
- After every accepted run made without a key (`noteRunAccepted`).
- On a 402, and on a 401 (to replace the token).
- When the allowance is spent, once just after `resets_at` (capped at 24h), so a tab left open overnight unblocks itself.

Concurrent reads share one request.

## Staying quiet

The banner shows only when there is no key, the read succeeded, and `enabled`
is true. A failed or offline read clears it rather than leaving a stale count
up. The one exception: after a 402, a failed confirm read keeps the limit state
up (`refusedSinceLastRead`), because the refusal is hard evidence. A saved key
hides the banner in the same render, through `useSyncExternalStore` over
`apiKeyStore`. The server snapshot is "no key", so prerendered HTML and
hydration agree.

## UI (IntakeFreeApp.png, IntakeLimitApp.png, IntakeWeb.png)

- One white strip above the "New analysis" eyebrow on **every** shell (installed app, phone web, desktop web; in the left column on desktop). The sentence is on the left and the near-black `btn btn-ink btn-pill` "Add key" is on the right.
- Copy: "**3 free runs left today.** Add your own key for more." The singular is "**1 free run left today.**". Signed out where sign-in is offered, the second sentence is "[Sign in] for 10 a day, or add your own key." (2026-11-14; "a month" until the daily account allowance the same day). When spent: "**You have used your free runs.**" with "Add your own key to keep going." on its own line, and the strip gets a `--color-danger-border` hairline. Nothing else turns red.
- "Add key" is a real link to `/app?view=api-key` (was `/?view=api-key` before Phase 5c moved the tool) (plain click goes through `goToMainTab`; middle-click opens a new tab).
- Blocked: Analyze link uses the existing `.btn-primary:disabled` grey. **Browse files is disabled too, and drop is refused** (`dropEffect = "none"`, no highlight). The board draws Browse looking normal, but a control that cannot succeed should not look pressable. The link field and the terms box stay usable, so a typed link survives saving a key and coming back.
- Accessibility: the `.free-runs-slot` wrapper is always rendered with `role="status"` (implicitly polite), so the count and the switch to "used" are announced without moving focus. It is `display: none` while empty.
- Large text (refinement 15): the "Add key" pill scales with the text, so at 200% it left the sentence one word a line. `.free-runs-slot` is now a size container (`free-runs`, font-size pinned to 1rem; the strip is all rem). Below **17em** of slot width the strip stacks: sentence on top at full width, pill underneath, left-aligned with it. 17em is where the sentence would get under ~9em of its own text beside the pill (5.68rem; padding, border and gap ~2.85rem). 320px at 100% has 18em and keeps the row, pixel-identical to before.
- Short desktop windows (`min-width: 60rem` and `max-height: 50rem`): while the banner is shown (`.intake-layout:has(.free-runs)`), the top padding drops to 1rem, the headline margin to 1rem, the banner's block padding to 0.5rem and its line-height to 1.35. Measured: 1366×768 fits with no scroll in all six states (3 left, spent, none × light/dark).

## Known issues

- At 1536×674 the intake already scrolls without the banner (587 vs 540 px content band; `upload-form.md`'s 2026-11-01 "no overflow at 1536×674" no longer holds). The banner adds about 46px there. Not addressed here.
- No frontend test runner. Verified with Playwright against mocked `/api/*` (see the mem entry).

## Unreachable server on launch (refinement 4, LCH-06)

A failed read still hides the pill, but it is no longer the only thing that
knew. `refreshFreeRuns` reports each result to
`application/serverReachability.ts` (`noteReadResult`), which flags
"unreachable" on a `NetworkError` only. `HomeScreen` shows a calm
`ReachabilityNotice` in the capability slot ("Can't reach the server right
now. You can still open past runs in History.", or "You're offline right now.
..." when `navigator.onLine` is false). `useFreeRuns` registers with
`onReconnectChance`: while the notice is up, `online`, window `focus` and
`visibilitychange` to visible re-read the allowance if it is still unknown, so
the pill appears on its own. Nothing is blocked. See
`capability-reporting.md` for the other half.

**Refinement 10: a 5xx counts as unreachable.** With the backend down,
Railway's edge answers every path with a 502/503, so the read did get "an
answer", the flag was cleared, and the intake showed nothing at all (no pill, no
notice). `noteReadResult` now flags unreachable for a `NetworkError` **or** an
`ApiError` whose `status` is 500 or above. A 4xx is the server itself refusing
and keeps clearing the flag. `capabilitiesGateway.ts` now passes `res.status`
into its `ApiError` too, so the two launch reads agree (otherwise a later
capabilities 503 without a status would clear what the free-runs 503 set).
Verified in `scratchpad\refine10\verify.py` with route interception: 500/502/503
on every `/api` path show "Can't reach the server"; 400 shows no notice; a
healthy reply on the next window `focus` clears it and the pill appears.

## Refinement 9 (2026-11-02) — staying current, and proving a refund

**Re-reads.** `revalidateFreeRuns()` (a no-op on the user's own key) runs:
- on `visibilitychange` to visible, and on Capacitor `resume` (via the new
  `NativeShell.onResume`, throttled to 1.5s), from `useFreeRuns`;
- whenever a run completes or fails (`useAnalysisRun.settleFreeRuns`);
- whenever the intake comes back (`status === "idle"` in HomeScreen), so
  "Analyze another" after a refunded run shows the refunded count.
`refreshFreeRuns` already dedupes in-flight reads.

**Refund line, only with proof.** On submit, `useAnalysisRun` keeps the
allowance it saw (`currentFreeRuns()`, null on an own key). When a run fails it
reads again. If `remaining` is back to the pre-submit value with the same
`resetsAt` (`provesRefund`), the failed view says "This didn't use one of your
free runs." Otherwise it says nothing. The backend stores `failed`
(`set_error`) before `_settle_free_run` refunds, so a poll can see the failure
before the refund lands. The client therefore re-reads once more after 2.5s
(`REFUND_RECHECK_MS`). Settling before `set_error` in `process_run` would remove
the race at its source. That is a backend decision, left to the owner.

Verified (mocked `/api/*`): refund visible immediately → line shown; refund
landing after the first failed poll → line shown after the recheck; no refund →
no line; BYOK → no line and zero `/api/free-runs` reads.

**Refinement 11: a partial outage shows the notice (D-R10-1).** Web QA round
8 found that with only one of the two launch reads failing (free-runs 503,
capabilities 200, or the other way round) no notice showed: the module held
one shared boolean, and whichever read answered last set it, so the healthy
read's success cleared the other's failure. `serverReachability.ts` now keeps
a per-read set of failing sources (`ReadSource = "free-runs" |
"capabilities"`); `noteReadResult(source, error?)` adds or removes only that
read, and the notice is up while **any** read's latest result is a
`NetworkError` or 5xx. It clears only when every read has since come back
healthy: a later launch, resume or refocus round re-reads the failing ones
(`useCapabilities` re-reads until it has a report; `useFreeRuns`' reconnect
listener now also re-reads when `isReadFailing("free-runs")`, since after a
402 the status is kept and "status is null" alone would miss it). A 4xx
counts as healthy for that read, as before. When a key is saved the free-runs
read stops, so `forgetReadResult("free-runs")` drops its entry (otherwise a
failure from before the key could hold the notice up with nothing to retry
it). Copy unchanged. Verified in `scratchpad\refine11\verify.py` by holding
both launch responses and releasing them in each order, three trials each:
free-runs 503 alone, capabilities 503 alone and both 503 all show the notice
(18/18); a refocus with one read still failing keeps it; a fully healthy
refocus clears it and the pill appears; 400 on either or both shows nothing.

## Account allowance (2026-11-13)

Owner decision: a signed-in account gets **10 free shared-key runs per UTC
calendar month**, tied to the account across devices, used *instead of* the
device's 3 per day while signed in. A saved Gemini key is still exempt.
Backend contract: `GET /api/free-runs` gains `"scope": "device" | "account"`
(account: `limit` 10, `resets_at` the first of next month 00:00Z); the 402
`free_runs_used` body gains `scope` too.

- **Bearer.** Nothing new in the gateway: `FetchFreeRunsGateway` already goes
  through the shared `ApiClient`, which adds `Authorization: Bearer` when
  someone is signed in and the server's `auth` capability is `ok` (the same
  path `/api/me` and run creation use). Verified in Chrome that the read
  carries it when signed in.
- **Scope.** `FreeRunsStatus.scope` (`domain/entities.ts`, `FreeRunsScope`).
  The gateway reads only a literal `"account"` as account; missing (an older
  server) or anything else is `device`. `ApiError.scope` carries the 402's,
  and `markFreeRunsUsed(limit, used, scope)` uses it (falling back to the last
  read's scope, then device).
- **Re-read on sign-in / sign-out.** `useFreeRuns(identity)` takes
  `authUser.ready ? (user?.id ?? "") : null` from `HomeScreen`. A change after
  the first known value calls `noteIdentityChanged()`: bumps an
  `identityEpoch`, clears the cached count and any 402 limit state, publishes
  `null` (the strip goes quiet rather than showing the other identity's
  number), and re-reads unless a key is saved. A read that was in flight under
  the old identity is not published; `refreshFreeRuns` notices the epoch moved
  and reads again. The first known value does not re-read: the launch read
  already waits for a stored session (`ApiClient`).
- **Refund proof** (`provesRefund`) now also requires the same `scope` before
  and after, so a sign-in between the two reads cannot pose as a refund.
- **Spent timer.** Unchanged code; for an account the reset is weeks out, so
  the 24h cap simply re-reads once a day.

**Copy** (only the scope changes the words; layout unchanged):

| Where | device (unchanged unless noted) | account |
|---|---|---|
| Analyze strip, runs left | "**3 free runs left today.** Add your own key for more." Signed out where sign-in is offered (`showAccount`, 2026-11-14): "**3 free runs left today.** [Sign in] for 10 a day, or add your own key." | "**7 free runs left this month.** Add your own key for more." |
| Analyze strip, spent | "**You have used your free runs.** Add your own key to keep going." | "**You have used this month's free runs.** Add your own Gemini key to keep going." (the server's 402 `detail`, word for word) |
| Analyze strip, spent, signed out where sign-in is offered (`showAccount`) | "**You have used your free runs.** Add your own key, or [sign in] for 10 free runs a day." (new; inline `.text-link` to `/app?view=account`, ink + 600 like the blocked note's link) | n/a |
| Blocked note in the intake card | "No free runs left today, so analyzing is paused." | "No free runs left this month, so analyzing is paused." (`UploadForm` `blockedScope`) |
| Account panel, Plan and usage card (2026-11-14; was the identity line) | "Runs left today" → "N of L on this device" | "Runs left today" → "N of L" (`limit` from the server; "this month" only if `period` says so), and "Resets at" → `resets_at` as a local clock time. See `auth-sign-in.md`, "Account refinement (2026-11-14)" |

The sign-in nudge is only on the spent device strip: that is where signing in
actually unblocks someone, and it adds no chrome. The "10" there is a
constant (`ACCOUNT_FREE_RUNS_PER_MONTH` in `FreeRunsBanner.tsx`) because a
signed-out caller has no account read to take it from; change it with the
backend's limit. No reset date is shown in the Account panel (kept short).
With a key saved, a 402 still shows the server's sentence verbatim as the
intake error (unchanged path).

Not verified in a browser: the signed-out spent strip with the sign-in link
(it needs signing the owner out, which was off limits); typecheck and build
cover it.

## Daily account allowance (2026-11-14)

Owner decision: a signed-in **free** account gets **10 runs per UTC day**,
not 10 a month (3 a day anonymous against 10 a month signed in made signing
in look like a downgrade). Anonymous devices stay at 3 a day; the paid plan
is unchanged (100 a month, extra runs billed).

- **Contract.** `GET /api/free-runs` gains `period: "day" | "month"` on
  every response: device `day`, free account `day` (`limit: 10`,
  `resets_at` next UTC midnight), paid `month`. `FreeRunsStatus.period` and
  `FreeRunsBanner.period` (`domain/entities.ts` `FreeRunsPeriod`). A server
  that does not send it yet is read by plan in `freeRunsGateway.normalise`:
  paid `month`, anything else `day`. A 402 `free_runs_used` is only ever the
  free plan, so `markFreeRunsUsed` publishes `day`.
- **Copy follows `period`, not `scope`.** The strip, the blocked note
  (`UploadForm` prop renamed `blockedScope` -> `blockedPeriod`), the Account
  identity line and the landing allowance line say "today" / "a day" for
  `day` and "this month" / "a month" for `month`.
- **Constant.** `ACCOUNT_FREE_RUNS_PER_MONTH` -> `ACCOUNT_FREE_RUNS_PER_DAY`
  (10) in `application/accountAllowance.ts`; importers: `FreeRunsBanner`,
  `LandingAllowance`, `LandingScreen`, `AccountPanel`.

| Where | free account (supersedes the "account" column above) |
|---|---|
| Analyze strip, runs left | "**7 free runs left today.** Add your own key for more." |
| Analyze strip, spent | "**You have used today's 10 free runs.** They reset tomorrow. Add your own Gemini key to keep going[, or upgrade]." (`limit` from the server; "today's free runs" if a 402 carried no limit) |
| Signed-out hints | "[Sign in] for 10 a day, or add your own key." / "...or [sign in] for 10 free runs a day." |
| Blocked note | "No free runs left today, so analyzing is paused." |
| Account identity line | "Free runs left today: N of 10" |
| Paid strip / identity | superseded the same day: see "Paid daily allowance" below |

The spent account sentence is the frontend's own, not the 402 `detail`: the
strip only renders from a status read or a 402, and "They reset tomorrow" is
a fixed fact of the daily period. The "account reset is weeks out" note on
the spent timer no longer applies to free accounts; their reset is hours
out, the same path as the device.

## Paid daily allowance (2026-11-14, owner)

The paid plan's included runs are **30 per UTC day** (was 100 a month).
Tiers: anonymous 3 a day, free account 10 a day, paid 30 a day with videos
up to 10 minutes and no Gemini key needed; extra runs past the 30 are billed
per run with a hard cap of 200 extra runs a calendar month.

- **Contract.** `GET /api/free-runs` and `GET /api/billing` `runs.period`
  answer `day` (limit 30) for paid. Both adapters now read a missing
  `period` as `day` for every plan (`freeRunsGateway.normalise`,
  `billingGateway.normalise`); only a literal `"month"` reads as a month.
  `BillingDetails.runs.period` is new.
- **Constants.** `PAID_RUNS_PER_DAY` (30) and `PAID_EXTRA_RUNS_PER_MONTH`
  (200) next to `ACCOUNT_FREE_RUNS_PER_DAY` in
  `application/accountAllowance.ts`. Quoted only where no paid read exists
  (the free plan's pitch, the "upgrade" hint, the extra-run cap, which no
  status body carries). `PAID_RUNS_PER_MONTH` in `AccountPanel` is gone.

| Where | Paid copy |
|---|---|
| Analyze strip, runs left | "**N of 30 runs left today.**" (no pill) |
| Analyze strip, past the 30 (`overage`) | "**You have used today's 30 runs.** Extra runs are billed at $X each, up to 200 a month." (no price known: "Extra runs are billed per run, up to 200 a month.") |
| Free account spent, billing on | "...Add your own Gemini key to keep going, or [upgrade] for 30 a day." |
| Account identity line | "Runs left today: N of 30" |
| 402 `extra_runs_cap` | "You’ve reached this month’s limit of N extra runs. Your included runs come back tomorrow." (was "Runs reset next month.", wrong once the included runs are daily) |

## Reserved strip height (2026-11-14, Android QA run 22)

The strip used to be inserted when the read landed, with no space reserved,
pushing the eyebrow, title, lede and intake card down ~93 css px at 412 and
~115 at 320 (CLS 0.079-0.118). Now, like `LandingAllowance`:

- `useFreeRuns` returns `pending`: no key saved and no read has answered for
  the current identity yet (`Snapshot.settled`, set by a successful read, a
  failed read or a 402; cleared on launch and by `noteIdentityChanged`).
- While `pending`, `HomeScreen` renders an invisible, `inert`, `aria-hidden`
  stand-in `FreeRunsBanner` (`FREE_RUNS_GHOST`: device, 3 of 3 left, sign-in
  offered: the first-visit sentence and the longest "runs left" one) inside
  the slot (`data-pending`). `.free-runs-ghost { visibility: hidden }`, so no
  skeleton text is ever seen and the slot is sized by the real strip markup
  at every width and font scale. The live region does not announce it.
- A saved key never shows the strip, but the prerender cannot know that, so
  a new pre-paint script (`BYOK_INIT_SCRIPT` in
  `infrastructure/apiKeyStore.ts`, last in `PRE_PAINT_SCRIPT`) stamps
  `<html data-byok>` when the key exists (presence only), and
  `:root[data-byok] .free-runs-slot[data-pending] { display: none }`.
  `useFreeRuns` keeps the stamp in step after hydration (never on the first
  render, which always reads "no key"). Its CSP hash is computed by
  `inject-csp.mjs` like the others (checked in `out/app.html`).

Measured (Playwright, chromium-1217, dev server, `/api/free-runs` mocked with
a 1.5 s delay, CLS summed from `layout-shift` entries):

| Case | 412 web / app | 320 web / app |
|---|---|---|
| Device, runs left (first visit) | 0.0000 / 0.0021 | 0.0000 / 0.0015 |
| Free account, runs left | 0.0000 / 0.0021 | 0.0179 / 0.0163 |
| Paid, runs left (one line, shorter) | 0.0194 / 0.0185 | 0.0566 / 0.0489 |
| Paid, past the 30 | 0.0000 / 0.0021 | 0.0179 / 0.0163 |
| Key saved | 0.0034 / 0.0074 | 0.0041 / 0.0027 |
| Free account spent (taller) | 0.1062 / 0.0912 | 0.1317 / 0.1099 |
| Read failed (reservation collapses) | 0.0842 / 0.0738 | 0.1223 / 0.1045 |

Known residue: a spent strip is taller than the stand-in, and a failed read
gives the reserved space back. Both are rarer than the runs-left states and
no worse than before; keeping a blank band up after a failure, or guessing a
spent state before the read, would each be wrong more often than it helps.
Not yet re-measured on the device (the QA run's own numbers were on Android).

## Changelog

- 2026-11-01 · frontend agent (Phase 5b) · created: device token store, free-runs gateway/port, `useFreeRuns` store, 401 retry-once and 402 limit state in `useAnalysisRun`, `FreeRunsBanner` on all shells, `UploadForm` `blocked`, API key lede and Privacy sentence
- 2026-11-01 · frontend agent (Phase 5c) · Add key now links to /app?view=api-key (via mainTabHref)
- 2026-11-02 · frontend agent (refinement 4) · free-runs read reports reachability; re-read on online/focus/visible while the unreachable notice is up (LCH-06)
- 2026-11-02 · frontend agent (refinement 9) · re-read on visibilitychange, Capacitor resume, run settle and intake return; failed view states "This didn't use one of your free runs." only when the re-read count proves the refund (2.5s recheck for the backend's set_error-before-refund ordering)
- 2026-11-02 · frontend agent (refinement 10) · 5xx from the free-runs (and capabilities) read now counts as unreachable, so a Railway 502/503 shows the "Can't reach the server" notice; 4xx unchanged
- 2026-11-02 · frontend agent (refinement 11) · per-read reachability (`noteReadResult(source, err)`, `forgetReadResult`, `isReadFailing`): the notice shows when ANY launch read is unreachable and clears only once every read is healthy again, so a partial 5xx outage is no longer hidden by the other read's success; 4xx and copy unchanged (D-R10-1)
- 2026-11-02 · frontend (refinement 15) · `.free-runs-slot` is an em size container; below 17em the strip stacks (pill under the sentence), so the sentence is never one word a line at large text; 320/100% unchanged
- 2026-11-13 · frontend agent · account allowance: `scope` on `FreeRunsStatus`/`ApiError` (missing = device), re-read on sign-in/sign-out with an identity epoch so a stale read is never published, scope-aware copy on the strip, blocked note and Account panel, and a quiet "sign in for 10 free runs a month" link on the spent device strip where sign-in is offered
- 2026-11-13 · frontend agent · `plan`/`overage` on `FreeRunsStatus`; paid strip "N of L runs left this month." (no pill), past the allowance with overage "Extra runs are billed at $X each." (not blocked); a spent free account adds ", or upgrade." (link to Account) when billing is on. See `billing.md`
- 2026-11-14 · frontend agent · device strip says "today"; signed out where sign-in is offered it adds one inline "Sign in for 10 a month, or add your own key." so the device and account tiers read as two tiers (Android QA); `ACCOUNT_FREE_RUNS_PER_MONTH` moved to `application/accountAllowance.ts`
- 2026-11-14 · frontend agent · free account allowance is daily (10/day): `period` (`day`|`month`) on `FreeRunsStatus`/`FreeRunsBanner`, inferred by plan when the server omits it; copy keyed on period ("N free runs left today", spent "You have used today's 10 free runs. They reset tomorrow.", hints "Sign in for 10 a day"); `blockedScope` -> `blockedPeriod`; `ACCOUNT_FREE_RUNS_PER_MONTH` -> `ACCOUNT_FREE_RUNS_PER_DAY`
- 2026-11-14 · frontend agent · paid plan is 30 runs a day: missing `period` reads as `day` for every plan; paid strip "N of 30 runs left today.", past the 30 "Extra runs are billed at $X each, up to 200 a month."; spent free account "...or upgrade for 30 a day."; 402 `extra_runs_cap` "Your included runs come back tomorrow."; `PAID_RUNS_PER_DAY` / `PAID_EXTRA_RUNS_PER_MONTH` in `accountAllowance.ts`
- 2026-11-14 · frontend agent · Android QA run 22: strip height reserved before the first read (invisible inert stand-in, `useFreeRuns().pending`, `Snapshot.settled`) and dropped pre-paint for key holders (`BYOK_INIT_SCRIPT` stamps `data-byok`); CLS at 412/320 ~0 for runs-left states, numbers and residue under "Reserved strip height"
- 2026-11-14 · frontend agent · copy table corrected to the code: the signed-out strip says "10 a day" and "10 free runs a day" (the table still said a month); `FreeRunsBanner.resetsAt` added for the Account panel's Plan and usage card, which replaces the identity line's count
- 2026-11-14 · frontend agent · refund line reads "This didn't use one of your runs." (UX fix spec batch a)
