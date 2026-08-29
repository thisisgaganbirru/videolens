# App shell layout

The one-viewport frame every tab renders inside, in the Terminal design
direction (see `design-direction-terminal.md` for what's locked and why).

**Files**
- `frontend/components/HomeScreen.tsx` — the shell for one tab: nav band, active view, footer band. Takes the tab as a prop; `RoutedHomeScreen` (same file) is the variant that reads it from the URL. Also the single caller of `useCapabilities()` — see `capability-reporting.md`.
- `frontend/components/AppNav.tsx` — the whole nav band as one component: brand, the four tab links, the mobile drawer, the theme toggle. Rendered by `HomeScreen` **and** `LegalShell`.
- `frontend/application/useMainTab.ts` — the tab as a property of the URL: `MAIN_TABS`, `mainTabHref`, `goToMainTab`, `useMainTab`.
- `frontend/app/page.tsx` — the `<Suspense>` boundary `useSearchParams` requires on a statically rendered route.
- `frontend/components/theme.ts` — the light/dark constants shared by the pre-paint script and the toggle.
- `frontend/app/layout.tsx` — `<html>`/`<body>`, the pre-paint theme script, and the `.viewport` flex column the shell sits in.
- `frontend/app/tokens.css` — palette, type, space, shape, motion tokens.
- `frontend/app/globals.css` — the shared class vocabulary (`.shell`, `.nav`, `.nav-tab`, `.tab-view`, `.workspace`, `.surface`, `.pane`, …).

## Structure

The shell is **locked to exactly one viewport** — `100dvh`, `overflow: clip`,
as a flex chain: nav band → active view (`flex: 1`) → footer band. Heights are
*measured* through that chain, never computed by subtracting a guessed constant
from `100vh`.

Two height traps worth knowing, both hit for real during the mockup work:

- `min-height: 100%` on the shell still lets it grow, so the page keeps a
  scrollbar when the ask was a fixed frame. `height: 100%` is what's needed.
  The shell carries `data-frame="fixed"|"flow"` to switch between the two
  deliberately.
- Anything sitting directly inside `.viewport` (which is `display: flex;
  flex-direction: column`) needs `shrink-0`, or it compresses and throws off
  every measured height below it. `UpdateBanner` and the standalone routes
  each set it for this reason.

**Nav** is a floating pill — translucent with `--color-nav-bg` tint (a soft visible green tint in light theme), `backdrop-filter`, pulled half a rem
past the shell gutter so it sits proud of the content. Four tabs: Analyze,
History, API Key, Releases. It is one component, `AppNav`, rendered by every
route — see "Tab routing" below for why that only became possible once the tabs
had addresses.

> The mockup draws **six** tabs. That is a mockup convenience, not the design:
> home/analyze are two states of the Analyze tab, and processing/failed are run
> states, not destinations. Don't port the nav literally.

**Analyze** is two ruled columns at `3fr / 7fr` separated by a single vertical
hairline. **Neither column is a bordered card** — structure comes from rules and
alignment. Only the results pane carries the `--color-paper-2` tint (`.results`),
while `.surface` on non-results tabs (History, API Key, Releases) remains transparent with `.tab-view .pane` dropping `padding-inline` to align flush left with section headers.
De-boxing was a specific fix: two bordered tinted rectangles side by side read
as a PowerPoint slide.

**Footer** is a compact bar — wordmark left, legal links right, hairline above.

## Responsive model

Real `@media` breakpoints, **mobile-first** (`min-width`). The mockup uses
desktop-first `@container` queries measuring `.viewport`, purely so one artifact
could show web and mobile via a demo switch; the design doc calls for inverting
that in the real implementation, and it is inverted here.

Mobile: nav collapses to wordmark · menu · theme, with tabs moving into a left
drawer over a dimmed scrim. Touch ergonomics come from `@media (pointer: coarse)`
(44px targets) rather than width, and hover-only affordances are made permanent
there and under `@media (hover: hover)`.

**The drawer bug, do not reintroduce:** `backdrop-filter` on `.nav` silently
makes it the containing block for every absolutely-positioned descendant *even
at `position: static`*. The drawer's `inset: 0` then resolves against the nav
pill and renders as a tiny scrolling box inside the nav row. The fix is
`backdrop-filter: none` at mobile width.

## Tab routing

The active tab is a **query param on `/`** — `/?view=history`, `/?view=api-key`,
`/?view=releases`, with no param (or `?view=analyze`) meaning Analyze. It used
to be `useState` inside `HomeScreen`.

**Query param, not `/history` `/api-key` route folders.** One page component,
one copy of the shell, and it survives `output: "export"` — which is what the
Capacitor build ships. Route folders would prerender the whole shell four times
and make every tab switch a document navigation.

Ownership follows `ARCHITECTURE.md`: reading and writing that URL is
orchestration, so it lives in `application/useMainTab.ts` next to
`useAnalysisRun`, not scattered through components. `domain/` and
`infrastructure/` were not touched — a URL is not an external system.

Three things about it are load-bearing:

- **`window.history.pushState`, not `router.push`.** Next has supported the
  native History API for search-param updates since 14.1 and keeps
  `useSearchParams` in sync with it. Unlike a router navigation it never asks
  for an RSC payload — which matters, because the Capacitor build is a static
  export with no server to ask. Measured: five tab switches, zero document
  navigations, a `window` property set before the first switch still alive
  after the last.
- **`push`, not `replace`.** The URL is a real address now, so a tab switch is a
  real navigation and back should undo it. Measured: three switches add exactly
  three history entries; back walks releases → api-key → history → analyze and
  only leaves the page from the first entry — which is where Capacitor's
  `@capacitor/app` default maps the Android hardware back button to
  `exitApp()`. It also means "open a run from History, press back" lands on the
  history list instead of dropping the user out of the app, which is the
  behaviour that decided it. The cost is a long back-stack if someone taps tabs
  repeatedly; `replace` was the alternative and it silently breaks the back
  button for the thing the user just did.
- **`useSearchParams` needs a `<Suspense>` boundary here.** Every route is
  statically rendered, so Next resolves search params on the client and paints
  the nearest fallback into the prerendered HTML; without a boundary
  `next build` fails outright. The boundary is in `app/page.tsx` because it is a
  framework requirement, not a design choice, and the fallback is a **real
  Analyze shell** (`<HomeScreen activeTab="analyze" />`) rather than a spinner
  — so the prerendered HTML is the finished page for `/`, the overwhelmingly
  common entry point. This is why `HomeScreen` takes the tab as a prop and only
  `RoutedHomeScreen` calls the hook: if `HomeScreen` read the URL itself the
  fallback would suspend too.

Because the tabs have addresses, the nav is now literally one component
(`AppNav`) on every route rather than two near-identical navs. `LegalShell`
passes `activeTab={null}` — on `/privacy` none of the four is where you are, so
none carries `aria-current`. The tabs are real `<a href>`, so middle-click,
ctrl-click and "copy link address" all work; `AppNav` intercepts only plain
left-clicks, and only when the route it's on can update in place.

## Theming

Light is the default on bare `:root`; dark overrides the 13 colour tokens under
`:root[data-theme="dark"]`. The toggle is **stateless by design** — it flips the
`data-theme` attribute on `<html>` and writes `localStorage["videolens_theme"]`,
and the sun/moon glyph swap is a pure CSS rule keyed off that attribute. No
React state, so no hydration mismatch and the correct glyph on first paint. A
small blocking script in `layout.tsx` stamps the attribute before first paint so
the choice doesn't flash.

**First visit with nothing stored is LIGHT**, regardless of
`prefers-color-scheme`. A product decision, not an oversight; a stored choice
still wins and this only covers the no-preference case. There is no
`@media (prefers-color-scheme: dark)` block anywhere in the stylesheets — light
is already the bare `:root` — so nothing fights the script. Measured on a fresh
profile with `prefers-color-scheme: dark` emulated: `data-theme="light"` at
`DOMContentLoaded` and at the first animation frame, i.e. before any paint.

The browser-chrome colour follows it. `viewport.themeColor` used to be a
`prefers-color-scheme` **pair**, which was right only while the app tracked the
OS; a dark-OS visitor would now get a dark strip above a light page. It is one
media-less tag carrying the light value, which the pre-paint script and
`toggleTheme` both re-point at whatever theme is actually in use. The three
places that need those two hex values import them from `components/theme.ts` so
they cannot drift. (`public/manifest.webmanifest`'s own `theme_color` is
separate and was not touched.)

## Tab-switch alignment

`.workspace` and the three single-column views (`history`, `api-key`,
`releases`) both carry `margin-top: var(--space-md)`. That match is load-bearing,
not decoration: it's what makes the micro-label land at the same height on every
tab so nothing shifts when you switch views. Idle Analyze is the exception and
correctly has no margin — it's the mockup's `home` view, a vertically-centred
intake with no label to align.

The three views opt in with a **`.tab-view` class**, replacing a selector that
enumerated their `data-view` names and would therefore have silently skipped a
fifth tab. `:not([data-view="analyze"])` was the other candidate and is wrong:
`legal` and `offline` are `<section data-view>` too and neither wants the
margin, so idle Analyze is not the only exception — just the documented one.
Measured after the change: `.col-label` lands at y=93 on all three tabs.

## Token discipline

Every colour, radius and measure in `globals.css` should reference a token in
`tokens.css`. Two violations were found and fixed in review, and they are the
shape the next one will take:

- `--radius-pill` was declared `2px` and had **no callers**, while `.nav`,
  `.theme-toggle` and the desktop nav buttons each hard-coded `999px`. A token
  that both lies about its value and goes unreferenced is worse than no token.
  It is now `999px` and wired to all three.
- `--measure` (40rem) is new: the reading measure, previously a bare literal
  inside `.prose` and therefore impossible to align a layout against. `.prose`
  and `.legal-body` both reference it, which is what guarantees a document's
  rules and paragraphs share a right edge.
- `--font-mono` was deleted — in a single-face theme it was a third name for
  `--font-body`.
- `--content-width` (48rem) was deleted when `/offline` moved onto `.shell`.
  Its only consumer was `.page-shell`, the last of the old page-level layout
  classes; with that gone it was a second, competing width alongside
  `--shell-width` with nothing referencing it.

`--safe-top` is the live exception and is left alone deliberately: `.shell`
applies `--safe-left/right/bottom` but not top, because `.nav-wrap`'s own
`padding-top` stands in for it. It is currently a token with no callers.
Wiring it means changing the nav's vertical position on every route, which is
a design change, not tidying.

`.wordmark::before` declares `content: "▮"` plainly and then upgrades to the
alt-text form `content: "▮" / ""` under `@supports (content: "x" / "")`. The alt
form is a single indivisible value, so an engine that cannot parse it (Safari
below 17.4) drops the **whole** declaration and the accent mark vanishes from
every nav in the app. Do not collapse this back into one rule.

## Known issues

- **Visually verified** against `mockups/terminal-redesign.html` via Playwright
  (Chromium, 1440×900 and 390×844, light and dark, plus iPhone 13 touch
  emulation). Confirmed: the mobile drawer renders full-height at the viewport
  (`x:0 y:0 w:272 h:844`) rather than trapped inside the nav pill — the
  `backdrop-filter` containing-block bug is absent; `pointer: coarse` and
  `hover: none` both match under touch, nav buttons measure exactly 44px,
  history rows 64px, and `.h-go` resolves to `opacity: 1`. The nav pill matches
  the mockup to the pixel (52–53px desktop, 62px mobile, identical padding).
  Not tested on a physical device — emulation only.
- The completed-run two-column layout is **not** visually verified: it needs a
  backend, and history/API-key were checked against a mocked `/api/runs`. The
  `.workspace` grid is unexercised visually.
- **The `--z-*` scale is aspirational.** Only `--z-banner` has a caller
  (`UpdateBanner`); `globals.css` improvises `1/3/4/5/10` inline and none of
  those match the declared `0/10/30/50`. Left alone deliberately in review:
  wiring it means changing live stacking values on a drawer whose paint order is
  verified correct (with the drawer open, `elementFromPoint` at the nav pill's
  centre returns `.menu-head`, so the drawer does cover the nav as intended).
  Not worth the regression risk for tidiness.
- ~~**The tab-alignment selector enumerates view names.**~~ Fixed — it is the
  `.tab-view` class now; see "Tab-switch alignment".
- **A deep link to `/?view=history` paints Analyze for one frame.** No static
  file can know the query string, so the prerendered HTML is always the Suspense
  fallback (the Analyze shell) and the real tab appears at hydration. Confirmed
  by fetching `/?view=history` directly: the served HTML contains
  `data-view="analyze"` and no history section. This is inherent to a statically
  exported app, not a bug in the routing — the alternative is a `null` fallback,
  which trades one wrong frame on deep links for a blank frame on *every* load.
  Landing on `/` — the common case — has no flash at all.
- ~~**`/offline` still has a brand-only nav.**~~ Fixed — `app/offline/page.tsx`
  now renders `<AppNav activeTab={null} />` like every other route, measured
  identical to `/privacy` at 1440x900 and 390x844 in both themes. The tabs do
  dead-end offline for the same service-worker reason the footer's legal links
  already did; that was accepted as the honest answer rather than worked
  around — see `legal-offline-routes.md` § "Why `/offline` renders live tabs
  that can land back on `/offline`".
- ~~**At 390px the footer sits 16px higher on `/` than on `/privacy`**~~ Fixed
  — the `flow` frame was applying the bottom safe gutter twice (once via
  `.shell`'s own `padding-bottom`, again via `.page-end`'s), where the `fixed`
  frame zeroed `.page-end`'s and applied it once. `.page-end` now carries a
  negative `margin-bottom` matching its `padding-bottom` (`globals.css`,
  mobile-first block), reaching back into the gutter `.shell` already reserves
  instead of stacking a second one; the padding itself stays, since it's what
  carries `.page-end`'s `--color-paper` fill to the bottom edge while the
  footer is mid-scroll. The one-viewport scroll model is unchanged — this only
  moves where the footer rests. All four routes now agree at y=800.1 at
  390x844; see `legal-offline-routes.md` § "The footer's 16px offset between
  `flow` and `fixed` — fixed" for the full measurement.
- **Switching tabs drops any other query param.** `mainTabHref` builds a fresh
  query string, so `/?utm_source=x` becomes `/?view=history` on the first tab
  click. Harmless today (nothing else reads a query param) and deliberately not
  worked around: preserving them means the rendered `href` differs from the
  pushed URL, which is a hydration problem traded for a param that doesn't
  exist yet.
- **Leaving and re-entering History refetches `/api/runs`.** Measured: two
  visits, two fetches. Unchanged by the routing work — the panels were and are
  conditionally rendered, so they unmount on tab change either way. Fixing it
  means caching in `useRunHistory` or keeping every panel mounted.
- **The shell is what makes `useCapabilities()` a single fetch.** `HomeScreen`
  is not unmounted by a tab switch (the tabs are a `pushState` query param), so
  its `useEffect([])` runs once per app *load*, not once per tab visit. That is
  why `UploadForm` and `ApiKeyPanel` take capability rows as props instead of
  calling the hook themselves — both are conditionally rendered, so a hook in
  either would refetch on every visit, the same way `useRunHistory` does. If a
  future change ever makes the shell remount per tab, that assumption breaks
  silently and the report starts refetching.
- `.label-count` exists in `globals.css` but has no caller — the mockup's
  "6 runs" counter. Wiring it needs the run count in `HomeScreen`, which today
  means either a second uncached `useRunHistory` fetch or lifting the hook and
  re-shaping `HistoryPanel`'s props. Left unwired deliberately; Tailwind purges
  the unreferenced rule, so it costs nothing to keep.
- When measuring against the mockup, note its nav sits ~24px lower than the
  app's. That is the mockup's own demo chrome (`.page`/`.viewport` preview
  frame plus the WEB|MOBILE switch), **not** an app regression — don't "fix" it.

**Tests**: none (see `run-analysis-hook.md`); verified via `npx tsc --noEmit`,
`npm run build`, and `npm run build:mobile`, plus a Playwright/Chromium pass
against the production server at 1440x900, 390x844 and iPhone 13 covering nav
parity, tab switching, back/forward, deep links, the drawer and both themes.
The Android hardware back button itself was **not** run on a device — browser
back/forward was measured and the Capacitor mapping is read from
`@capacitor/app`'s documented default (`history.back()` while `canGoBack`, then
`exitApp()`).

## Changelog

- 2026-08-15 · frontend agent (foundation) · rebuilt the shell to the Terminal direction: one-viewport flex chain, pill nav, mobile drawer, 4 tabs, theme toggle
- 2026-08-15 · main session · added the tab-alignment margin so History/API key/Releases match .workspace; verified nav + drawer geometry with Playwright
- 2026-08-15 · frontend agent (pipeline review) · wired --radius-pill (was a dead 2px token against three hard-coded 999px), added --measure, dropped dead --font-mono and the dead .pull rule the sweep missed, made the wordmark glyph survive Safari <17.4 via @supports; logged the aspirational --z-* scale and the brittle tab-alignment selector as known gaps
- 2026-08-15 · frontend agent (offline chrome) · deleted .page-shell and --content-width once /offline moved onto .shell (last callers); renamed .legal-title → .page-title as it now serves offline too; recorded --safe-top as an intentionally unwired token. Shell/nav/footer geometry unchanged — see legal-offline-routes.md
- 2026-08-15 · frontend agent (url tabs + light default) · moved the active tab into the URL (`/?view=…`) via application/useMainTab.ts + a Suspense boundary in app/page.tsx; extracted the whole nav band into components/AppNav.tsx so LegalShell renders the same four tabs (measured identical to `/` at 1440x900 and 390x844); `.nav-links > button` → `.nav-tab` and the tab-alignment selector → `.tab-view`; `data-menu-open` moved from `.shell` to `.nav-wrap`; first visit with nothing stored now defaults to LIGHT and the theme-color meta follows the theme instead of prefers-color-scheme
- 2026-08-29 · frontend agent · `HomeScreen` now calls `useCapabilities()` once and owns the always-present `.cap-slot` live region inside `.intake`; the slot is zero-height and carries no CSS on a healthy deployment, so the idle Analyze layout is unchanged (measured identical). New `.cap-*` block in globals.css sits after `.error-inline`
- 2026-08-15 · doc-accuracy agent · marked two Known issues fixed against live code: `/offline` now renders `<AppNav activeTab={null} />` (was brand-only), and `.page-end`'s negative `margin-bottom` closes the 16px flow-vs-fixed footer gap at 390px (was open) — both cross-checked against `legal-offline-routes.md`, which had already recorded the fixes and flagged this doc as stale
