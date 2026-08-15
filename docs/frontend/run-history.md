# Run history panel

Shows the caller's own past runs (newest first, backend-capped at 20) and lets them reopen one.

**Files**
- `frontend/application/useRunHistory.ts` — fetches on mount via `runsGateway.listRuns()`; classifies failures and owns the retry.
- `frontend/infrastructure/runsGateway.ts` — `FetchRunsGateway`; the only place that knows whether a call failed in transport or in HTTP.
- `frontend/domain/errors.ts` — `ApiError` and `NetworkError`, the two-case error contract every gateway method obeys.
- `frontend/components/panels/HistoryPanel.tsx` — renders loading/error/empty/list states; each item shows title (or "Untitled run"/"Failed run" fallback) and `formatDate(created_at) · status`.
- `frontend/components/format.ts` — the shared `formatDate` helper (also used by the release-notes panel).

**Ownership**: history is scoped server-side by the caller's `Principal` (see `backend/docs/auth.md` — anonymous callers are scoped by `X-Client-ID`), not filtered client-side.

**Layout** (Terminal redesign — see `design-direction-terminal.md`): single
column. Runs are bucketed by day into `.history-group` headers derived from
`created_at`; status is a colour-coded `.h-dot` reading down the left edge
rather than a word. History rows (`.history-row`), group headers (`.history-group`),
and flat states align flush left with section headers.

**Render only what `RunSummary` carries.** It is exactly `run_id`, `status`,
`title`, `created_at` (`domain/entities.ts:53`) — **there is no platform,
duration, or thumbnail, because the API doesn't return them.** A duration and a
status pill were both drawn in an early mockup pass and removed once checked
against source. The day label and the 6-char short-hash run ID are *derived*
from real fields, not new data.

State hooks: `.history-row[data-run-status]`, and `.h-title[data-fallback]`
which mutes the "Untitled run" / "Failed run" fallbacks.

## The four states, and how a failure is worded

Three of them are unchanged: `runs === null` → a muted `.pending-note`
"Loading…" (`role="status"`), `runs.length === 0` → a muted `.pending-note`
"No previous runs yet." — **the empty case is a 200 with `{"runs": []}` and is
not an error**, and a populated response → the day-grouped list.

The fourth used to collapse every failure into one red box reading "Could not
load history." That string was reachable *only* when the request never reached
a server at all (see the diagnosis in
`mem/20260815-terminal-redesign-implementation.md`), so the one case it
described was the one case it got wrong. It now splits three ways:

| what happened | where it's decided | what the user sees |
| --- | --- | --- |
| `fetch` itself rejected — backend down, DNS, offline, blocked CORS preflight | `FetchRunsGateway.send` throws `NetworkError` | "Can't reach the server. It may be offline, or your connection dropped." |
| the server answered non-2xx | `ApiError(body.detail …)` — unchanged | the backend's own `detail`, verbatim |
| a 2xx whose body will not parse | `FetchRunsGateway.parse` throws `ApiError` | "The server replied with something this app could not read." |

`useRunHistory` maps those to `{ kind: "unreachable" | "server" | "unknown",
message }` **by domain error class, never by inspecting the raw error's shape
or text** — `err instanceof TypeError` in a hook or a component is exactly the
layering violation the two error classes exist to prevent. The panel renders
`message` as-is and puts `kind` on `data-error-kind` for tests; it writes no
copy of its own.

**Retry.** The effect is keyed on an `attempt` counter, so `retry()` re-runs the
same code path the mount uses. While a retry is in flight the error stays on
screen with the button labelled "Retrying…" and marked `aria-disabled` — it is
deliberately *not* `disabled`, because a focused element that becomes
`disabled` is blurred to `<body>` and a keyboard user loses their place
mid-retry. The guard against double-submit is in the hook. There is also no
flip back to the "Loading…" note on retry, for the same reason: the control the
user is standing on has to survive a second failure.

**Presentation — `.error-inline`, not `.error-block`.** `.error-block` is the
one deliberately bordered object in a boxless system and is sized for a whole
view having failed (bold lead, explanatory paragraph, and a button its
`p:last-of-type` reserves bottom margin for). Rendered around a single sentence
inside a panel it carried full-view weight *plus* dead space where the missing
button should be. `.error-inline` (`globals.css`, next to `.error-block`) is the
panel-scoped treatment: no box and no fill, a 2px `--color-danger` left rule,
`max-width: var(--measure)`, and 0.8rem body text — the same size
`.history-row`'s title uses, one notch above `.pending-note`'s 0.74rem because a
failure outranks "Loading…", and well below the 0.92rem of a failed view.
`.error-block` is untouched and still correct for `RunStatusView.tsx`'s
`data-view="failed"` state. **`VersionLogPanel` had the same one-bare-`<p>`
misuse of `.error-block` and has since moved to `.error-inline`**
(`components/panels/VersionLogPanel.tsx`), with `role="alert"` (not
`role="status"` — the earlier reasoning for `status` was "nothing to act on,"
which the retry retires) and a real retry via `application/useVersionLog.ts`,
which mirrors this hook's shape: an `attempt` counter, a `retrying` flag, a
guarded `retry()`, and `setError(null)` on success.

The retry control is the project's own `.btn .btn-secondary`; it needs no
bespoke touch rule because `@media (pointer: coarse)` already sizes every
`.btn`.

**The failure ladder, four rungs, documented in `globals.css` at
`.pending-note`.** Pick by what the thing *is*, not by how bad it feels:
`.pending-note` (one neutral line — nothing is wrong, content is absent or
pending) → `.error-note` (**the same line at `--color-danger`** — something was
rejected and the control that caused it is right there, so no box and no
recovery control of its own) → `.error-inline` (a panel-scoped failure region
with a retry control) → `.error-block` (the whole view failed). `.error-note`
was added in the same pass at the request of the agent working on
`HomeScreen`/`VersionLogPanel`: the recipe already existed inlined at
`UploadForm.tsx:258` (`text-[0.74rem] leading-[1.6]
text-[var(--color-danger)]`), and a rejection shipped on plain `.pending-note`
measured **5.26:1** (light) / **5.53:1** (dark) against paper — lighter than the
terms copy beside it, so it landed as a footnote. On `.error-note` the same
line measures **6.89:1** / **6.99:1**, above both the 4.5:1 floor and the
neutral note it sits among. Rendered and compared side by side at 390px in both
themes, not just computed.

**The classifier is now shared.** What `useRunHistory` did inline above has
been lifted to `application/gatewayError.ts`'s `classifyGatewayError(err,
fallback)` — same by-domain-error-class rule (`NetworkError` → `"unreachable"`,
`ApiError` → `"server"`, anything else → `"unknown"` plus a caller-supplied
fallback sentence), same refusal to inspect the raw error's shape or text.
It lives in `application/`, not `domain/`, on purpose: `domain/errors.ts` owns
the error *classes* — the contract between a gateway and its callers — while
this maps those classes onto a UI-shaped `{ kind, message }` plus a
feature-specific fallback sentence, which is orchestration and copy, not a
contract. It stays free of React and of `fetch` so any hook in the layer can
call it. `useRunHistory` re-exports its two types as `RunHistoryErrorKind` /
`RunHistoryError` so `HistoryPanel`'s public vocabulary didn't have to change
when the classifier moved out.

`useAnalysisRun.ts` now uses the same helper and exposes `errorKind` alongside
`error`, so a backend that is *down* is reported with the honest connectivity
sentence instead of `"Could not submit media."` / `"Could not load that
run."` — those two strings are now fallbacks only, reached when a failure is
neither a `NetworkError` nor an `ApiError`. One asymmetry is deliberate, not a
gap: when a run's own `status` comes back `"failed"`, `error` is set from the
backend's own reason but `errorKind` is left `null` — that failure came from
the run itself, not from a transport classification, so there is no `kind` to
report.

One real bug was fixed during the redesign —
`groupByDay` emits a group per *contiguous* run of equal labels, and an
unparseable `created_at` yields `"Undated"`, which can appear in multiple
non-adjacent groups and produced duplicate React keys. Now keyed by index.

**Tests**: none (see `run-analysis-hook.md` — no frontend unit tests currently).
All four states have now been exercised in a real browser (Playwright against a
mock `:8000` — stopped for the transport case, 503-with-`detail`, `{"runs":[]}`,
and populated) at 1440x900 and 390x844 in both themes: retry recovers the list,
the empty state is still a muted note, the retry target measures exactly 44px
on touch, and there is no horizontal overflow.

**One app-wide fix fell out of that measurement** and lives outside this
feature: `.btn` carries `all: unset`, which also resets `box-sizing` to
`content-box`, so `@media (pointer: coarse)`'s `min-height: 2.75rem` was
painting 66.8px buttons (44 content + 20.8 padding + 2 border) instead of the
44px it reads as. `.btn` now re-declares `box-sizing: border-box`, the way
`.history-row` already did for exactly this reason. Every `.btn` in the app is
44px tall on touch as intended; verified on the analyze intake as well as here.

## Changelog

- 2026-08-15 · frontend agent · ported HistoryPanel to day-grouped rows with status dots; fixed duplicate React keys on non-adjacent "Undated" groups
- 2026-08-15 · frontend agent (history error handling) · split transport from server failures (`NetworkError`), added a keyboard-reachable retry, replaced the panel's `.error-block` with a new `.error-inline`, added `.error-note`, and fixed `.btn`'s `content-box` touch targets (66.8px → 44px)
- 2026-08-15 · doc-accuracy agent · corrected two stale claims against live code: `VersionLogPanel` has moved to `.error-inline` with a real retry (was recorded as not-yet-done), and `useAnalysisRun.ts` now classifies via the shared `application/gatewayError.ts` (`classifyGatewayError`) and exposes `errorKind` (was recorded as an open follow-up); documented the shared classifier itself
