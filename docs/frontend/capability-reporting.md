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

**1. The intake strip (`CapabilityNotice`).** A collapsed two-line readout above
`UploadForm`, expanding to the full per-row table. Collapsed it says only what
is affected:

```
unavailable — daily budget                              DETAILS ⌄
degraded — url download
```

One line per severity rather than a sentence: at `.intake`'s 34rem in a
monospace face, a sentence naming three capabilities wraps to three lines
anyway.

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

## Visual language

Same left-ruled, boxless geometry as `.error-inline` — the same kind of object
(a scoped condition inside a view that is otherwise fine), so it does not invent
a second idiom. It is deliberately **not** `.error-block`, which is the single
bordered object in a boxless system and is sized for a whole view having failed.

Severity is carried by the rule's ink and by the words, never by a new hue. The
palette declares exactly one danger token and no warning token: `unavailable`
takes `--color-danger`, `degraded` keeps the neutral `--color-rule-2` on the
rule and separates from `ok` by ink weight (`--color-ink` vs `--color-muted`).
This is the same restraint `.status[data-tone="stalled"]` uses when it declines
to be a fourth severity. Adding an amber here is how a two-accent system becomes
a traffic light — don't.

`.cap-state` and `.cap-unverified` are both `0.6rem`, matching `.history-group`,
so nothing here introduces a new smallest type size.

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
- `.cap-summary` gets `min-height: 2.75rem` under `@media (pointer: coarse)`,
  measured at 340.0 × 57.1 at 390px.

## Known issues

- **Expanded, the strip is tall.** Six rows with details push the drop zone and
  terms checkbox below the fold at 390×844, and off a 900px-tall desktop
  viewport. Accepted: it is opt-in (the user tapped `details`), the idle Analyze
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

## Changelog

- 2026-08-29 · frontend agent · added the capability surface: `CapabilitiesGateway` port + `FetchCapabilitiesGateway` adapter (normalising, not casting), `useCapabilities` hook fetched once in `HomeScreen`, the `CapabilityNotice` intake strip with a `probed`-aware disclosure, and `CapabilityCallout` wired to the URL field and the API-key panel; extracted `infrastructure/apiBase.ts` so two adapters share one origin
