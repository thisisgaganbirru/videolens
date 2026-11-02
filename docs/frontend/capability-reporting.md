# Capability reporting (frontend)

Surfaces `GET /api/capabilities` — the deployment saying which of its parts
actually work — so a user learns a source will not work **before** spending an
upload on it. Before this, a stale yt-dlp or a missing cookie file meant
uploading, waiting through the pipeline, and getting *"Media analysis failed.
Please try again."* See `docs/backend/capabilities.md` for what each row means,
what `probed` is for, and why the endpoint always answers 200.

**Files**
- `frontend/domain/entities.ts` — `CapabilityState`, `Capability`, `CapabilityReport`.
- `frontend/domain/ports.ts` — `CapabilitiesGateway`.
- `frontend/infrastructure/capabilitiesGateway.ts` — `FetchCapabilitiesGateway`.
- `frontend/infrastructure/apiBase.ts` — `API_BASE_URL`, extracted from `runsGateway.ts` so two adapters share one origin.
- `frontend/infrastructure/container.ts` — registers `capabilitiesGateway`.
- `frontend/application/useCapabilities.ts` — the hook, plus the exported `isNoticeable` predicate.
- `frontend/components/CapabilityNotice.tsx` — the intake strip (default export) and `CapabilityCallout` (the one-row contextual note).
- `frontend/components/HomeScreen.tsx` — the single caller of the hook; owns the `.cap-slot` live region and passes the two rows down.
- `frontend/components/UploadForm.tsx` — the `url_download` note under the URL field.
- `frontend/components/panels/ApiKeyPanel.tsx` — the `daily_budget` note.
- `frontend/app/globals.css` — the `.cap-*` vocabulary (in the `CAPABILITIES` block, directly after `.error-inline`).

## Three surfaces, one fetch

**1. The intake notice (`CapabilityNotice`).** A compact card, collapsed to one
sentence-case line ("Unavailable right now: media processing. Limited: link
downloads.") with a "Details" toggle that opens the full per-row list. It sits
at the top of the "What you get" column on a wide screen and first on a phone,
never between the lede and the intake card. See "Visual language" below; the
Terminal-era two-line uppercase readout this section used to show is gone.

**2. `url_download` under the URL field.** `URL runs may fail — <backend
detail>` (or *are unavailable* at that state). Wired to the input as
`aria-describedby`, not announced by a live region, so a screen-reader user
meets it when they focus the field rather than competing with the strip's
announcement on load.

**3. `daily_budget` in the API-key panel.** The backend's own sentence,
verbatim: *"Today's shared run budget is exhausted. Bring-your-own-key runs are
unaffected."* This panel is the answer to that row, which is why it lives here
and nowhere else.

`HomeScreen` calls `useCapabilities()` **once** and passes the two rows down as
props. That is deliberate: `HomeScreen` is never unmounted by a tab switch (the
tabs are a `pushState` query param — see `app-shell-layout.md`), so one call is
one request per app *load*. Had `UploadForm` and `ApiKeyPanel` each called the
hook, both are conditionally rendered and it would have been one request per tab
visit. No polling: a capability report is deployment shape, which changes on a
redeploy, not between two clicks.

## Decisions worth not re-litigating

**Nothing renders when the deployment is healthy.** `ok` shows nothing.
A permanent "all systems operational" strip is chrome that tells the user
nothing they can act on. A **fifth nav tab** was the other candidate and was
rejected for the same reason — a tab advertises a health check on a healthy app
— with the added cost that it would have to exist on every route. Operators who
want the report on a green deployment have `curl /api/capabilities`, which is
what the backend doc points them at.

**`disabled` is never a fault.** It renders as the words `not configured` in
muted ink, with no severity mark, and it can never make the strip appear. Object
storage unconfigured in local dev is deployment shape; the backend already
excludes `disabled` from its aggregation, and re-deriving severity in the UI is
the obvious place to accidentally put it back. `ok` and `not configured` share
the same muted ink — a green tick beside an unconfigured optional dependency
would make it look like a lesser kind of broken.

**`probed: false` is a visible tag, not a tooltip.** Each unprobed row carries
an outlined `UNVERIFIED` mark next to its state word, and the expanded region
ends with a legend: *"unverified — read from this deployment's configuration and
not checked against the live dependency."* A caveat you have to hover to find is
a caveat that was hidden, and this distinction is the honest core of the whole
feature.

**Warn, never block.** A `degraded`/`unavailable` `url_download` does **not**
disable the URL field. The probe reads a yt-dlp build date and whether a
configured cookie file exists; neither proves the specific link the user is
about to paste will fail. Disabling on that evidence would refuse URLs that work.

**Failure is silent, and the silence lives in the hook.** The adapter throws
like every other gateway — deciding a failure does not matter is not its job.
`useCapabilities` swallows it and leaves `report` at `null`. Missing health
information is not itself a health problem, and *"could not check whether the
service is healthy"* is pure noise on a service that is in fact fine.

**The adapter normalises; `runsGateway`'s `parse<T>` casts.** The divergence is
deliberate and follows from the promise above: this must never hand the hook a
`capabilities` that is `undefined` and turn a health feature into a render crash
on the intake. Rows without a `name` are dropped; anything that is not literally
`probed: true` is treated as unprobed, because the ambiguous case has to fall on
the honest side.

**Unknown names and states render, they are not filtered.** `name` is
`String.replace(/_/g, " ")`, so `url_download` → `url download` with no lookup
table to fall out of date and a capability added server-side appearing correctly
on an old build. An unrecognised `state` renders as itself in neutral ink. A UI
about honesty that silently drops rows it does not recognise is lying by
omission. `mode` (`local`/`distributed`) is the one field deliberately **not**
rendered — it names a topology with no user-visible consequence the rows do not
already state (`run_store`'s detail already says "runs are lost on restart").

## Visual language (editorial Phase 2, 2026-11-01)

The Terminal-era treatment (left rule, uppercase `UNAVAILABLE` / `OK` /
`NOT CONFIGURED`, boxed `UNVERIFIED` tags, uppercase `HIDE ^`) is gone. No board
covers this state, so it follows `design-direction-editorial.md`:

- **Collapsed by default, one compact card**: a status dot, one sentence-case
  line, a "Details" text button. Same surface and edge family as `.run-notice`
  (`--color-surface`, 1px `--color-rule`, `--radius-control`).
- **The sentence is label-first** — "Unavailable right now: media processing.
  Limited: link downloads." — so it never has to agree a verb with a name it
  does not control (plural or not, known or added server-side later).
- **Red only for an actual failure.** `unavailable` paints the dot, the card's
  edge (`--color-danger-border`) and its state word in danger; `degraded` gets a
  neutral (`--color-muted`) dot and the word "Limited". Still no warning token,
  no amber.
- **Expanded rows** are plain words: name (ink, 600) on the left, state on the
  right in sentence case — Working / Limited / Unavailable / Not set up — with
  "· not checked" in muted ink for `probed: false`, then the backend's detail
  verbatim. A legend explains "not checked" only when some row is unchecked.
- **Names**: a small map gives plain names (`media_tools` → "Media processing",
  `url_download` → "Link downloads", …); anything unknown still falls back to
  the backend name with underscores replaced, so new rows render on old builds.
- **The one-row callout** (`CapabilityCallout`, under the URL field and in the
  API-key panel) is a dot plus "**Link runs may fail.** <backend detail>", no
  card and no rule.
- **Placement**: `.cap-slot` moved out of `.intake` to be a grid item of
  `.intake-layout` — top of the "What you get" column from 60rem, first item
  (above the eyebrow) on a phone. It no longer sits between the lede and the
  card, so the card does not move: measured card top 462px at 1086×900 with and
  without the notice, collapsed or expanded.

## Accessibility

- `.cap-slot` is **always** in the DOM with `aria-live="polite"`, empty and
  zero-height when healthy. It carries no CSS at all — in particular no
  `:empty { display: none }`, which would take the live region out of the
  accessibility tree and stop it ever announcing the report it exists to
  announce.
- `.cap-detail` stays in the DOM while collapsed, hidden with the `hidden`
  attribute, so `aria-controls` never points at an element that does not exist.
  `.cap-detail[hidden] { display: none }` is required to beat the flex display.
- The URL note is `aria-describedby` on `#media-url`, composed with the existing
  `intake-error` id rather than replacing it.
- The toggle is `.cap-toggle`, a real `<button>` with `aria-expanded` /
  `aria-controls`, 44px tall at every pointer (and in the coarse-pointer list),
  2px accent focus ring at 2px offset. It is no longer the whole line: the
  summary sentence is a plain `<p>`, so the announced text is not a button
  label.

## Known issues

- **Expanded, the notice is tall on a phone.** On a wide screen it expands in
  the panel column and moves nothing on the left. On a phone (first item) six
  rows push the form down. Accepted: it is opt-in (the user tapped `details`), the idle Analyze
  view is on the `flow` frame so the content band scrolls, and collapsing
  restores the form. Not worked around — capping the region's height and giving
  it its own scroller puts a second scroll context inside a one-viewport shell.
- **A backend newer than the build can report a state with no matching row.**
  If overall `state` is degraded/unavailable but no capability admits to it, the
  strip falls back to a single `service state — <state>` line rather than
  rendering an empty warning. Verified by serving `{"state":"degraded"}` with no
  `capabilities` key.
- **No retry.** A failed fetch is not retried and there is no control to retry
  it; the report is fetched once on mount and that is the whole lifecycle. A
  reload is the recovery. Adding retry means adding a visible failure state,
  which is precisely what "degrade silently" rules out.
- **`analysis_engine` and `run_store` are `probed: false` in the common local
  setup**, so the expanded table shows three `UNVERIFIED` tags on a perfectly
  healthy deployment. That is the backend being honest, not a display bug — but
  it does mean the table reads more cautious than the app feels.
- The strip never appears on the History or Releases tabs. Neither has an action
  a capability row changes; the two that do are wired directly.

**Tests**: none (no frontend test runner — see `run-analysis-hook.md`). Verified
with `npx tsc --noEmit`, `npm run build`, and a Playwright/Chromium pass against
`next start` with `/api/capabilities` mocked, at 1440×900 and 390×844 (touch),
light and dark:

| check | result |
|---|---|
| healthy report | 0 `.cap-notice`, `.cap-slot` present at 0px height, intake pixel-identical |
| degraded report | summary `["unavailable — daily budget", "degraded — url download"]`, detail hidden until clicked, 6 rows, 3 `UNVERIFIED` tags |
| `disabled` row | state word `not configured`, ink equal to `--color-muted` and not equal to `--color-danger`, in both themes |
| URL field | callout rendered, `aria-describedby="url-capability"`, input **not** disabled |
| API key tab | backend sentence verbatim |
| fetch aborted | 0 notices, intake visible, URL field usable, 0 page errors |
| 404 (older backend) | 0 notices, 0 page errors |
| `{"state":"degraded"}` with no `capabilities` | 1 notice reading `service state — degraded`, 0 page errors |
| 390px touch | `.cap-summary` 340.0 × 57.1, `pointer: coarse` matches, 0px horizontal overflow collapsed **and** expanded |

Contrast against paper, light / dark: summary unavailable line 6.89 / 6.99 at
12.48px · summary degraded line 18.1 / 16.82 · `DETAILS` affordance 7.66 / 10.69
· row name 18.1 / 16.82 · row state (unavailable) 6.89 / 6.99 at 9.6px · row
state (not configured) 5.26 / 5.53 · `UNVERIFIED` tag text 5.26 / 5.53 · row
detail 5.26 / 5.53 · legend 5.26 / 5.53 · URL callout 18.1 / 16.82. The
`UNVERIFIED` tag's *outline* measures 2.36 / 2.62 against paper, below the 3:1
non-text threshold — accepted, because the tag's meaning is carried by its text
(5.26 / 5.53), not by the box, so WCAG 1.4.11 does not apply to it. It uses
`--color-rule-2`, the same token `.status[data-tone="stalled"]` and `.drop` use.

Not tested on a physical device — emulation only, and never against a live
backend (the fixture is the exact payload shape in `docs/backend/capabilities.md`).

## Unreachable notice (refinement 4, LCH-06)

Decision (1) above, "failure is silent", still holds for the report itself,
but a launch with the server unreachable looked identical to a healthy one.
`useCapabilities` now reports each fetch to `application/serverReachability.ts`
and, if the first fetch never arrived, fetches again when that module signals
a reconnect chance (`online`, window `focus`, page visible; only while the
notice is up). Decision (2) holds on a healthy launch: one request (verified:
capabilities, free-runs and runs once each; a focus event adds nothing).

`components/ReachabilityNotice.tsx` renders in `.cap-slot` (the polite live
region) in place of the capability notice while unreachable or offline: the
same `.cap-notice` card, neutral dot, one sentence and a "History" link
(`?view=history`). Never red, never blocks the form. Verified at 390x844 and
844x390, light and dark: notice up and Analyze enabled with `/api/*` refusing
connections; after the server returns, a focus event removes it and the
free-runs pill appears; offline (`navigator.onLine` false) shows the offline
wording, and a visibilitychange after coming back clears it.

Installed app (refinement 5, LCH-06d): android-66 saw "Can't reach the
server" in airplane mode, not the offline wording. The logic is right
(`offline` is `navigator.onLine === false`, checked first), but Android WebView
only feeds connectivity into `navigator.onLine` and the `online`/`offline`
events when the app holds `ACCESS_NETWORK_STATE`; the manifest had only
`INTERNET`, so `onLine` stayed true and the offline branch was unreachable in
the app (the quiet retry on `online` never fired either; focus/visibility
still did). Added the permission (normal, install-time, no prompt) to
`AndroidManifest.xml`. Whether this WebView version honours it is unverified
here (Chromium has gated it on that permission; not confirmed for current
builds); both wordings remain true if it does not.

Known gap: coming back online after an offline spell during which every read
had *succeeded* does not probe again, so a server that went down meanwhile is
only discovered on submit (the offline flag knows nothing about the server).

## Changelog

- 2026-08-29 · frontend agent · added the capability surface: `CapabilitiesGateway` port + `FetchCapabilitiesGateway` adapter (normalising, not casting), `useCapabilities` hook fetched once in `HomeScreen`, the `CapabilityNotice` intake strip with a `probed`-aware disclosure, and `CapabilityCallout` wired to the URL field and the API-key panel; extracted `infrastructure/apiBase.ts` so two adapters share one origin
- 2026-11-01 · frontend agent · editorial restyle: compact collapsed card (dot, sentence-case label-first line, Details toggle), red only for `unavailable`, sentence-case states with inline "not checked", plain names map with fallback; callout de-ruled; notice moved to its own intake grid cell (top of the panel column / first on phone) so the intake card no longer moves
- 2026-11-02 · frontend agent (refinement 4) · added the shared reachability flag, retry on reconnect, and the ReachabilityNotice in the capability slot (LCH-06)
- 2026-11-02 · frontend agent (refinement 5) · LCH-06d: offline branch unreachable in the app because WebView needs ACCESS_NETWORK_STATE for navigator.onLine; permission added to the manifest (device check pending)
