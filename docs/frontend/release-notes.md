# Release notes / version log panel

Shows the "Releases" tab: a list of GitHub releases for this repo, most recent first.

**Why this comes from our own backend, not GitHub and not a static file**: the
repo is private, and GitHub's REST API 404s (not 403s) on unauthenticated
requests to a private repo's releases, to avoid leaking whether it exists.
Calling GitHub from the browser therefore always fails, and a token cannot ship
in client-side JavaScript — so the read has to happen somewhere that can hold a
credential.

For a long time that place was CI: the job that publishes the release already
holds the ambient token every GitHub Actions run gets for free, so it wrote the
answer into `frontend/public/releases.json` and **committed it back to `dev`**,
and the browser read it same-origin. That bot commit is what forced the move.
GitHub does not trigger workflows for `GITHUB_TOKEN` pushes, so the commit
carried no checks, and Railway's `Wait for CI` then either deployed it ungated
(no PR open) or skipped the deploy entirely (PR open, checks stuck at
`action_required`) — see `../railway-environments.md`.

The read now happens server-side, in `GET /api/releases`
(`../backend/releases.md`). The token stays on the server, the client asks its
own backend, and nothing writes to git. The trade is that the tab is no longer
same-origin: it depends on the backend being reachable and on `ALLOWED_ORIGINS`
including the frontend's origin, the same as every other API call this app
makes.

**Files**
- `frontend/infrastructure/versionLogGateway.ts` — `FetchVersionLogGateway`, does `fetch("${API_BASE_URL}/api/releases")` and maps the endpoint's snake_case rows (`published_at`) to `VersionLogEntry`'s camelCase (`publishedAt`), so `domain/` never sees the wire shape. A body whose `releases` is not an array is rendered as empty rather than raised as an error.
- `frontend/application/useVersionLog.ts` — fetches on mount; owns the retry (an `attempt` counter the effect is keyed on, mirroring `useRunHistory`).
- `frontend/components/panels/VersionLogPanel.tsx` — renders loading/error/empty/list states.
- `GET /api/releases` — the producer, documented in `../backend/releases.md`. Reads GitHub with a server-held token, caches 300s, serves the last good answer if a refresh fails, and returns `{"releases": []}` rather than an error when no token is configured.

**Shared with** `frontend/infrastructure/updateCheck.ts` (native-Android in-app
update banner), which reads the *same* endpoint for its `latest` field. The two
consumers used to read two separate CI-written static files
(`releases.json` and `version.json`); one endpoint now answers both, and the
`releases[]` / `latest` split in the response is exactly that division —
`releases[]` is the changelog this panel renders, `latest` is the single build
number an installed APK compares itself against.

**Design status — extrapolated, needs review.** The Terminal mockup never drew
this panel, so `VersionLogPanel` was ported by analogy to the history list:
hairline-separated rows, square, no fill, no shadow. Two deliberate divergences
from history worth a look: the releases pane *keeps* its side padding (the
`padding-inline: 0` rule is scoped to `[data-view="history"]`), so rows read as
text lines rather than full-bleed bands; and consequently hover recolours the
title to `--color-accent` instead of painting an inset fill, which looked wrong
inside a padded pane. It reuses `.h-text`/`.h-sub` but deliberately *not*
`.h-go`, which is hidden by default outside a hovered `.history-row` and would
be permanently invisible on desktop — a lucide `ExternalLink` is used instead.
The sub-line is `tag · formatDate(publishedAt)`, both genuinely on
`VersionLogEntry` (`domain/ports.ts:18`).

## The error state — `.error-inline` with a retry

`useVersionLog` sets its one error string when the `fetch` of
`/api/releases` rejects or answers non-2xx: the device is offline, the backend
is down or unreachable, or the origin is not in its `ALLOWED_ORIGINS`. (Before
2026-08-29 the same string covered a same-origin `fetch("/releases.json")`
failing because the device was offline or the manifest was missing from the
build.)

That state has now been on all four rungs of the ladder `globals.css` documents
above `.pending-note`, so the reasoning is worth writing down once.

- It started as `.error-block` — the one bordered object in a boxless system,
  which the locked mockup draws exactly once, for a *failed run*, around a bold
  lead, an explanatory paragraph and a retry button. Around a single bare `<p>`
  it wore full-view weight plus the dead space `p:last-of-type` reserves for the
  button that wasn't there.
- It was then demoted to `.pending-note`, deliberately as a stopgap: the rung it
  wanted did not exist yet and that agent was correctly barred from adding CSS.
  The cost was measured rather than assumed — a rejection on plain
  `.pending-note` is **5.26:1** light / **5.53:1** dark against paper, *lighter*
  than the neutral copy beside it, so a failure read as a footnote.
- It is now **`.error-inline`**, the panel-scoped failure region, **and it is
  that rung because it now carries a retry.**

**Why not `.error-note`,** the rung below, which would also have fixed the
contrast. Read literally, `.error-note` is defined as a rejection sitting
*beside the control that caused it* — which is why it needs no box and no
recovery control of its own (`UploadForm`'s terms note is the shape it was
written for). Nothing here was user-triggered; the fetch happens on mount. So
`.error-note` describes this state no better than `.error-inline`-without-retry
does. Both rungs were a fit only if something changed, and the honest change is
the one that supplies what was actually missing: **recovery**. The named cause
is being offline, and being offline ends. Before this, the only way back was a
full reload or the accident of switching tabs and back (which remounts the panel
and refetches) — a path the user has to discover rather than one the app offers.

The second argument is consistency. Releases and History are the same object one
tab apart: a fetch-on-mount gateway list with loading / empty / error / list
states. `HistoryPanel` already renders `.error-inline` with a
`.btn .btn-secondary` retry. Two identical shapes with different recovery
affordances is exactly the drift the written-down ladder exists to stop.

**`role="alert"`, not `role="status"`.** The earlier `status` was justified by
"nothing is lost and there is nothing to act on"; the retry retires the second
half of that, and `HistoryPanel` — same object, same region, same control — is
already `alert`. Both roles are implicit live regions; `alert` is assertive,
which costs nothing here because the region appears on tab-open rather than
mid-reading.

**The retry mechanics are `useRunHistory`'s, deliberately.** The effect is keyed
on an `attempt` counter so `retry()` re-runs the mount path rather than a second
async callback that has to be kept in step with it. While a request is in flight
the button reads "Retrying…" and is marked `aria-disabled` — **not** `disabled`,
because a focused element that becomes `disabled` is blurred to `<body>` and a
keyboard user loses their place. The double-submit guard lives in the hook. The
error stays on screen during a retry (no flip back to "Loading…") so the control
the user is standing on survives a second failure.

**Known gap this does not fix.** `FetchVersionLogGateway` throws a plain
`Error` for both a rejected `fetch` and a non-2xx, so the hook writes one
generic string ("Could not load the version log.") rather than the honest
wording `useRunHistory` gets from `NetworkError` / `ApiError` (see
`run-history.md`). Still open after the move to `/api/releases`: the endpoint
swap was deliberately kept behaviour-neutral, and `capabilitiesGateway.ts` is
the sibling to copy when someone closes it. It also means retry is offered for
causes it cannot fix — a backend with no GitHub token, or an origin the backend
does not allow — which is the same trade `HistoryPanel` already accepts for a
repeatable 5xx, and is why repeated failure is designed to leave the control in
place rather than to promise success.

**Empty is not an error.** A backend with no `GITHUB_TOKEN` configured answers
`{"releases": []}`, which renders the empty state, not the error state. That is
deliberate and matches what the static file did before CI had ever written to
it — "nothing to show" is a real answer for a changelog.

**Tests**: none — this is a static file maintained by CI shell/Node, not
application code with meaningful unit-testable logic. See `run-analysis-hook.md`
for the project's general test-coverage stance on frontend gateways.

All four panel states have been exercised in a real browser (Playwright/Chromium
against the static export, the response **forced** with `page.route` rather than
reasoned about) at 1440x900 and 390x844 with `hasTouch`, light and dark. That
run predates the move to `/api/releases`, so the route it intercepted was
`/releases.json`; the panel, the hook and the four states are unchanged, but
anyone re-running it must now intercept `${API_BASE_URL}/api/releases` and
return the endpoint's snake_case shape:

- error region `role="alert"`, 2px `--color-danger` left rule, 0.8rem (12.8px)
  body text; zero `.error-block` and zero `.error-note` in the view
- contrast from painted sRGB (computed style returns `lab()` for these tokens,
  so each colour is repainted as a swatch and the pixel read back): region text
  **10.80:1** light / **10.83:1** dark, danger rule **6.89:1** / **6.99:1** —
  versus the 5.26 / 5.53 the same sentence measured on `.pending-note`
- retry button **107.9 x 44.0** under `pointer: coarse` (exactly 44, i.e. the
  `.btn` `box-sizing` fix holds here too — 66.8 would be the regression) and
  42px on desktop; horizontal overflow 0 everywhere
- retry recovers: one failed fetch, then a fulfilled one, renders both fixture
  rows; during flight the label is "Retrying…" with `aria-disabled="true"`, no
  `disabled` attribute, and focus stays on the button
- retry that fails again: focus still on the button, label back to "Try again",
  `aria-disabled` cleared, error still on screen; a second click while busy is
  swallowed by the hook's guard
- loading and empty are unchanged and stay visually distinct — muted
  `.pending-note` at 11.84px, no rule and no control

One trap worth recording for the next person who does this: the service worker
precached `/releases.json`, and a SW-served fetch bypasses Playwright's
`page.route` entirely. The first load is uncontrolled so the forced failure
works, but the *retry* silently hit the real file and the test looked like the
retry did nothing. Contexts must be created with `serviceWorkers: "block"`. The
cross-origin `/api/releases` call is not precached, so the specific trap is
gone — but `serviceWorkers: "block"` stays the right default for this harness.
Separately, `next.config.mjs` currently sets `output: "standalone"`, so
`next start` cannot serve this build (it logs the warning and 500s on the RSC
routes) — the export in `out/` served over a plain static server is the working
harness.

## Changelog

- 2026-08-15 · frontend agent · ported VersionLogPanel by analogy — no drawn spec, needs a design review pass
- 2026-08-15 · frontend agent (error block weight) · demoted the error state from .error-block to a role="status" .pending-note, matching its loading/empty siblings
- 2026-08-15 · frontend agent (version log error) · promoted the error state to `.error-inline` and gave `useVersionLog` a real retry (attempt counter + `retrying`), so it earns that rung rather than borrowing it; `role="status"` → `role="alert"`
- 2026-08-15 · main session · updated release-manifest ownership after the Android dev workflow was split from monolithic CI
- 2026-08-15 · main session · updated the release-manifest workflow path to the descriptive naming convention
- 2026-08-29 · frontend agent · repointed the panel's gateway from the CI-committed `/releases.json` onto `GET /api/releases`; `StaticVersionLogGateway` → `FetchVersionLogGateway`, snake_case→camelCase mapped at the adapter boundary
