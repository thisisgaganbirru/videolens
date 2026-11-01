# Run history panel

Shows the caller's own past runs (newest first, backend-capped at 20) and lets them reopen one.

**Files**
- `frontend/application/useRunHistory.ts` — fetches on mount via `runsGateway.listRuns()`; classifies failures and owns the retry.
- `frontend/infrastructure/runsGateway.ts` — `FetchRunsGateway`; the only place that knows whether a call failed in transport or in HTTP.
- `frontend/domain/errors.ts` — `ApiError` and `NetworkError`, the two-case error contract every gateway method obeys.
- `frontend/domain/entities.ts` — `RunSummary` (with the Phase 3 optional fields), `RunSourceKind`, `RunPlatform`, `RunOrientation`.
- `frontend/components/history.ts` — **pure** helpers, no React: `posterTint` (FNV-1a of `run_id` → 1..5), `platformLabel`, `isAudio`, `isLandscape`, `formatDuration`, `posterBadge`, `posterTitle`, `dayBucket`, `posterDate`, `matchesFilter`, `matchesQuery`, `sortRuns`, `buildHistory`, `posterLabel`.
- `frontend/components/panels/HistoryPanel.tsx` — renders the page header, the four states, the controls and the poster grid. Props: `onOpenRun(runId, sourceKind?)`, `onAnalyze()`.
- `frontend/components/HomeScreen.tsx` — renders `<section data-view="history">` (no `.col-label`/`.surface`/`.pane` any more) and passes the summary's `source_kind` on to `openRun`.
- `frontend/app/globals.css` — the HISTORY block (`.history*`, `.filter-pill`, `.sort-select`, `.poster*`), hover rules in `@media (hover: hover)`, and the History section scroller next to Analyze's.

**Ownership**: history is scoped server-side by the caller's `Principal` (see `backend/docs/auth.md` — anonymous callers are scoped by `X-Client-ID`), not filtered client-side. Filtering *within* the returned list (pills, search, sort) is client-side.

## Layout — poster grid (Phase 3, 2026-11-01)

Source of truth: `design/shots/HistoryA.png`, `HistoryADark.png`,
`HistoryMobile.png` (installed app), `HistoryWeb.png` (phone browser).

- **Header**: `h1.history-title` "History" in Newsreader (36→48px), lede
  "Your recent analyses. Open one to read its notes again."
- **Controls** (populated state only): filter pills All / Instagram / TikTok /
  YouTube / Files (`button[aria-pressed]` in a `role="group"`; active = filled
  ink pill), search (`input[type=search].field.field-pill`, matches title +
  `summary_snippet`, every whitespace term must match), sort (native `<select>`
  styled as a pill: Newest / Oldest). From 48rem: pills left, search (260px) +
  sort right. Phone: search with sort beside it, then the pill row, which
  scrolls sideways and bleeds off the right edge. A visually hidden polite
  status announces "N runs shown" only once something has narrowed the list.
- **Groups**: `h2.history-group-label` eyebrows TODAY / EARLIER THIS WEEK /
  EARLIER (+ UNDATED for an unparseable `created_at`, always last). "This
  week" = the previous six calendar days, the window where a bare weekday
  ("Thu") is unambiguous. Oldest-first reverses the group order too.
- **Grid**: `ul.poster-grid`, 2 columns → 3 (40rem) → 4 (52rem) → 5 (64rem),
  `grid-auto-flow: row dense`, `align-items: start`. Landscape runs
  (`orientation === "landscape"`) `grid-column: span 2` with a 16:9 thumb;
  everything else (including null orientation) is a 3:4 portrait.
- **Poster**: the whole card is one `<button class="poster">` whose
  accessible name starts with the title (`posterLabel`). Thumb = flat
  `--poster-N` tint picked by a stable hash of `run_id`; platform chip top-left
  (surface pill), round play disc centred (waveform `AudioLines` for
  `audio_file`), badge bottom-right. Under it: title (600, wraps) and date
  ("Today, 9:41 PM", "Yesterday, …", "Thu, 7:02 PM", "Oct 12, 7:02 PM", year
  added outside the current one). Focus: 2px green ring, 4px offset, around the
  whole card. Hover: 4% ink veil + play disc scale 1.06 (opacity/transform
  only; the global reduced-motion rule collapses them).
- **Fallbacks for legacy rows** (every new field is optional and nullable):
  no platform → "Link"/"File" chip from `source_kind`, else no chip; no
  duration → no badge; no orientation → portrait; no title → muted "Untitled
  run". **Run state outranks duration** in the badge slot: `failed` → "Failed"
  (danger-soft fill, danger text, danger-border hairline — muted, red only
  because it is an error), `queued`/`processing` → "Processing" (surface
  pill). Failed and in-progress runs still count toward the backend's 20.
- **Files filter** = `source_kind === "file"` or platform `audio_file` /
  `video_file`.
- **Scrolling**: like Analyze, from 32rem `section[data-view="history"]` is the
  scroller between the fixed nav and footer (full-bleed so its scrollbar is at
  the window edge); below 32rem `.viewport` scrolls. In the installed-app shell
  the dock's footprint is already reserved by `.shell`'s bottom padding —
  measured at 390×844 scrolled to the end: last poster bottom 700, dock top 764.

**Retired**: `.history-list`, `.history-row`, `.h-*` (status dot list from the
Terminal redesign) and the "Render only what `RunSummary` carries" rule — the
backend now sends platform, duration, snippet and orientation.

## The four states, and how a failure is worded

Three of them keep their semantics, restyled in Phase 3: `runs === null` →
a muted `.pending-note` "Loading your runs…" (`role="status"`),
`runs.length === 0` → `.history-empty` (serif "No runs yet.", one line, and an
"Analyze a video" secondary button that goes to the intake) — **the empty case
is a 200 with `{"runs": []}` and is not an error**, and a populated response →
the poster grid. A fifth, client-side state: filters/search that match nothing
→ `.history-empty` "No runs match." with a "Show all runs" button that resets
the filter and the query (the sort is kept).

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
- 2026-11-01 · frontend agent (Phase 3) · replaced the day-grouped row list with the editorial poster grid (filters, search, sort, day buckets, landscape spans, tint hash, legacy fallbacks, Failed/Processing badges); pure helpers in components/history.ts; History section is now its own scroller; empty + no-matches states restyled
