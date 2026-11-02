# App shell layout

The one-viewport frame every tab renders inside. Visual system:
`design-direction-editorial.md` (2026-11-01; the Terminal direction it replaced
is kept as history). The frame mechanics below — flex chain, measured heights,
URL tabs — carried over unchanged; the chrome around them did not (see "Two
shells").

**Files**
- `frontend/components/HomeScreen.tsx` — the shell for one tab: nav band, active view, footer band. Takes the tab as a prop; `RoutedHomeScreen` (same file) is the variant that reads it from the URL. Also the single caller of `useCapabilities()` — see `capability-reporting.md`.
- `frontend/components/AppNav.tsx` — the top bar as one component: brand, the four tab links (desktop, web shell), theme toggle, phone hamburger + full-screen menu panel. Exports `TAB_LABEL`. Rendered by `HomeScreen`, `LegalShell` and `/offline`.
- `frontend/components/SiteFooter.tsx` — the web shell's footer (one copy; was three).
- `frontend/components/BottomTabBar.tsx` — the installed-app dock: Analyze, History, More. Owns the More sheet's open state.
- `frontend/components/MoreSheet.tsx` — the More `<dialog>`; contents are `MORE_SHEET_GROUPS` (data).
- `frontend/components/shell.ts` — `ShellMode`, `SHELL_STORAGE_KEY`; `navClick.ts` — `isPlainLeftClick` shared by every nav.
- `frontend/application/useMainTab.ts` — the tab as a property of the URL: `MAIN_TABS`, `mainTabHref`, `goToMainTab`, `useMainTab`.
- `frontend/app/page.tsx` — the `<Suspense>` boundary `useSearchParams` requires on a statically rendered route.
- `frontend/components/theme.ts` — the light/dark constants shared by the pre-paint script and the toggle.
- `frontend/app/layout.tsx` — `<html>`/`<body>`, the pre-paint theme script, and the `.viewport` flex column the shell sits in.
- `frontend/app/tokens.css` — palette, type, space, shape, motion tokens.
- `frontend/app/globals.css` — the shared class vocabulary (`.shell`, `.nav`, `.nav-tab`, `.view-scroll`, `.view-head`/`.view-title`, …).
- `frontend/components/useMediaQuery.ts` — `useSyncExternalStore` wrapper over `matchMedia` (server snapshot `false`); for the rare case where React, not just CSS, must know the width (History's hidden sort).
- `frontend/components/AppBackLink.tsx` + `frontend/application/backNavigation.ts` — the installed app's "‹ Back" link above the title of API key, Releases, Privacy and Terms, and the "is the previous entry in-app?" check behind it. See "App-shell Back link".

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

**Nav (Terminal era — replaced 2026-11-01, see "Two shells").** Was a floating pill — translucent with `--color-nav-bg` tint (a soft visible green tint in light theme), `backdrop-filter`, pulled half a rem
past the shell gutter so it sits proud of the content. Four tabs: Analyze,
History, API Key, Releases. It is one component, `AppNav`, rendered by every
route — see "Tab routing" below for why that only became possible once the tabs
had addresses.

> The mockup draws **six** tabs. That is a mockup convenience, not the design:
> home/analyze are two states of the Analyze tab, and processing/failed are run
> states, not destinations. Don't port the nav literally.

**Analyze (Terminal era — replaced 2026-11-01, Phase 2).** Was two ruled
columns at `3fr / 7fr` separated by a hairline, with the results pane on a
tinted `.results` surface. Phase 2 rebuilt all three states (intake two-column
card + "What you get", progress filmstrip, results source column + card); see
`upload-form.md`, `run-status-pipeline.md`, `results-view.md`.

**Analyze scrolling (Phase 2).** At ≥ 32rem the whole `section[data-view="analyze"]`
is the scroller (`overflow-y: auto`) and is full-bleed — `margin-inline: calc((100% - 100cqi) / 2)`
with matching padding — so its scrollbar sits on the window edge, not inside
the gutter. `HomeScreen` no longer sets `data-frame`; the section scrolls only
when its content is taller than the band (measured: Main at 1280×989 is
855/855, no scroll; ResultsTranscript at 1280×980 is 846/846). Below 32rem the
`.viewport` scrolls, as before. The footer band at ≥ 32rem reaches back through
the shell's bottom gutter (`margin-bottom: -max(1rem, safe-bottom)`), so it sits
on the window's bottom edge as drawn (y 932 at 1280×989, same as Main.png).
History joined Analyze in Phase 3. **Phase 4 (2026-11-01) made it universal:** every view section is `<section class="view-scroll">` — Analyze, History, API key, Releases on `/`, plus `/privacy`, `/terms` and `/offline` — and the three scroller rules in `globals.css` target `.shell > section.view-scroll` instead of listing `data-view`s. `data-frame="fixed"` is no longer set by any route (its CSS remains, unused). The Terminal-era panel frame — `.tab-view`, `.surface`, `.pane`, `.home-center`, `.legal-doc`, `.legal-body`, `.page-title` — is deleted. `.col-label`/`.card-label` survive only for the dev preview harnesses. A new view: render `section.view-scroll`, then a centred column (`.key-page`/`.releases`/`.legal-page` share one 43.5rem rule) with a `.view-head` (`h1.view-title` + `.view-lede`).
De-boxing was a specific fix: two bordered tinted rectangles side by side read
as a PowerPoint slide.

**Footer** is a compact bar — "VideoLens AI" left, underlined Privacy/Terms right, full-bleed hairline above. Shown in the web shell and in installed windows wider than 37.5rem; hidden only in the phone-width app shell (≤ 37.5rem), which has the dock instead.

## Responsive model

Real `@media` breakpoints, **mobile-first** (`min-width`). The mockup uses
desktop-first `@container` queries measuring `.viewport`, purely so one artifact
could show web and mobile via a demo switch; the design doc calls for inverting
that in the real implementation, and it is inverted here.

Mobile (< 48rem, web shell): the bar is brand · theme · hamburger, and the
hamburger opens a full-screen menu panel in place of the content (the drawer and
scrim are gone as of 2026-11-01). Touch ergonomics come from `@media (pointer: coarse)`
(44px targets) rather than width, and hover-only affordances are made permanent
there and under `@media (hover: hover)`.

**The drawer bug (historical — drawer removed 2026-11-01; still true of any future overlay), do not reintroduce:** `backdrop-filter` on `.nav` silently
makes it the containing block for every absolutely-positioned descendant *even
at `position: static`*. The drawer's `inset: 0` then resolves against the nav
pill and renders as a tiny scrolling box inside the nav row. The fix is
`backdrop-filter: none` at mobile width.

## Two shells (2026-11-01)

`<html data-shell="web"|"app">` is stamped before first paint (detection and the
`videolens_shell` testing override: `design-direction-editorial.md`). Every route
renders **both** chromes; CSS shows one.

| | web (browser tab) | app (installed PWA / Capacitor) |
|---|---|---|
| Top bar | brand · tab links (≥ 48rem) · theme · hamburger (< 48rem) | ≤ 37.5rem: brand · theme only. Wider: same as web (links ≥ 48rem, hamburger between) |
| Phone menu | `.menu-panel`, sibling of `.nav-wrap`, full-width 60px cards; hides the content section while open | none at ≤ 37.5rem |
| Bottom | `SiteFooter` | ≤ 37.5rem: `BottomTabBar` (fixed dock, inset by `--page-gutter`/safe areas), no footer. Wider: `SiteFooter`, same as web |
| Privacy / Terms | footer | ≤ 37.5rem: More sheet rows. Wider: the footer (owner decision 2026-11-01; not added to the top-bar menu) |

**Phone-only dock (Phase 2).** The bottom tab bar, the More sheet and the
content's dock clearance all live inside `@media (max-width: 37.5rem)`, and
so (since 2026-11-01) does the app shell's footer hide — a wider installed
window gets the web chrome whole, top bar and footer. CSS only — nothing in
React reads the width. Measured: 1024×760 and 700×800 app shell show the top
bar and the footer, no dock; 390×844 app shell shows the dock and no footer;
390 app shell content ends 64px above the dock top.
Known edge: if the More sheet is open and an installed window is widened past
37.5rem, the dialog stays open (its trigger is now hidden); Escape or the
backdrop still closes it.

This is a **deliberate exception to "same footer on every route"**, now
confined to the phone-width app shell: the rule is "same chrome on every route
*within a shell*". Both shells still render on
`/`, `/privacy`, `/terms`, `/offline`.

- **Content never sits under the dock.** In app mode `.shell` gets `padding-bottom: calc(var(--tabbar-height) + max(var(--space-sm), var(--safe-bottom)) + var(--space-sm))`, so the scroller's last line clears the bar. Measured at 390×844: dock top 764, Analyze content ends 565, legal scroller ends 748.
- **Top bar is sticky, full-bleed.** `.viewport` is `container-type: inline-size`; `.nav-wrap` and `.page-end` break out of the shell's gutter with `margin-inline: calc((100% - 100cqi) / 2)` + matching padding — full width without `100vw` (which counts the scrollbar and causes horizontal scroll).
- **More sheet** is a native modal `<dialog>` opened with `showModal()`: top layer, inert page, Escape via `cancel`, `::backdrop` click closes (dialog has no own padding, so only a backdrop click targets the element), focus returns to More on every close path. Add rows by editing `MORE_SHEET_GROUPS` — three row kinds: `tab` (in-place nav on `/`), `route` (plain `<a>`, works from `/offline`), `theme` (`role="switch"`, reuses `toggleTheme`).
- **Cascade-layer trap.** The responsive `@media` blocks in `globals.css` are *unlayered*, so they beat anything in `@layer components` regardless of specificity. The ≥ 48rem `.nav-links { display: flex }` is therefore written `:root:not([data-shell="app"]) .nav-links` — unscoped, it would resurrect the links in app mode. Any new unlayered responsive rule touching chrome needs the same guard.

### App-shell Back link (2026-11-01)

The Phase 4 crumb/back bar stays **removed in the web shell** (desktop and
phone browser). In the **app shell only** (`html[data-shell="app"]`), API key,
Releases, Privacy and Terms carry a small `‹ Back` link (`.app-back`,
`components/AppBackLink.tsx`) above the title — they open from the More sheet,
and iOS standalone has no back button.

- **Visibility is CSS.** `.app-back` is `display: none`; `:root[data-shell="app"] .app-back` is `inline-flex`. Same layer (`components`), no media query, so it shows at every app width (an iPad in standalone has no back button either). `data-shell` is stamped pre-paint, so no flash; `display: none` keeps it out of the tab order and the accessibility tree in the web shell (measured: 0 `link "Back"` in phone web and 1366, 1 in app).
- **Look.** Lucide `ChevronLeft` + "Back", Hanken 15px/500, `--color-muted`, ink on hover/active/focus, 2px `--color-focus` ring (`outline-offset: 0`, `--radius-control`). The 44px target is padding pulled out with negative margins (12px up into the column's top padding, 6px left so the chevron sits on the title's edge), so the title moves down only ~32px: measured at 390×844 app, title top 132 vs 100 in the web shell; link box 69×44.
- **Behaviour** (`application/backNavigation.ts` → `hasInAppPrevious()`). A real `<Link href="/">` (middle-click / copy link = Analyze). Plain left-click: if the previous history entry is in-app → `history.back()` (returns to the view the user came from: a tab on `/` or a legal route); else on `/` → `goToMainTab("analyze")` (push, like any tab switch); else (legal route opened cold) the link navigates to `/`. "In-app previous" is, in order: Navigation API `navigation.currentEntry.index > 0` (same-origin entries only); else the `videolensInApp` marker `goToMainTab` now writes into every entry it pushes (Next's patched `pushState` keeps its own `__NA`/tree keys beside it — measured); else a same-origin `document.referrer` (Privacy/Terms are document navigations from the More sheet's plain `<a>`).
- **Measured** (Playwright, mocked `/api`, app shell 390×844), with and without the Navigation API (`window.navigation` shadowed to `undefined`): Analyze → More → API key → Back = `/` Analyze; History → More → Releases → Back = `/?view=history`; History → More → Privacy → Back = `/?view=history`; Analyze → More → Terms → Back = `/`; cold `/?view=api-key`, `/?view=releases`, `/privacy`, `/terms` → Back = `/` Analyze. 16/16 pass.
- **Not covered:** a tab view reached by a *Next router* navigation (e.g. the More sheet's API key row tapped on `/privacy`) on a browser **without** the Navigation API has no marker and no useful referrer, so Back goes to Analyze instead of the legal page. Chromium and Safari 26+ take the Navigation API path and are unaffected.

## Tab routing

**Phase 5c (2026-11-01): the tabs moved from `/` to `/app`.** Read every `/`
and `/?view=…` in this section and in "App-shell Back link" as `/app` and
`/app?view=…`. The mechanism is unchanged: `pushState`, `useSearchParams`, the
Suspense boundary (now in `app/app/page.tsx`). What changed:

- `application/useMainTab.ts` exports `APP_PATH = "/app"`, `isAppPath()`
  (accepts `/app`, `/app/` and `/app.html`, the Capacitor spelling) and
  `mainTabHref(tab, base)`. `goToMainTab` pushes onto the current path if it is
  an app path, else onto `/app`.
- `AppBackLink` and `backNavigation.ts` use `isAppPath()` where they used to
  compare with `/`.
- `/` is the landing (`landing-page.md`). Old `/?view=…` addresses redirect to
  `/app?view=…` before paint.
- **The brand.** In a browser tab the brand is a `<Link href="/">` (to the
  landing) with `aria-current="page"` on `/`. In the installed shell it is a
  plain `<span>`: the installed app has no landing to go to. `AppNav` renders
  both (`.brand--link`, `.brand--static`) and CSS keyed on `data-shell` shows
  one, so the right one is there at first paint.
- The landing renders the same chrome (`AppNav activeTab={null} landing`,
  `SiteFooter`, `BottomTabBar activeTab={null}`).


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
`toggleTheme` both re-point at whatever theme is actually in use.

**Android status bar sync from the More sheet.** The More sheet's theme row
calls the same `toggleTheme()` as the top-bar `ThemeToggle`. The native status
and navigation bars follow via `useSystemBarsTheme`, which is mounted inside
`ThemeToggle` and observes `<html data-theme>` — and `AppNav` renders
`ThemeToggle` in both shells, including app mode at phone width where the
sheet is the visible control. So a switch from the sheet re-colours the system
bars with no extra wiring. Not re-verified on a device in Phase 2 (agents do
not run the native build); reasoned from the mount point. The three
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

`--safe-top` was wired into `.nav-wrap`'s `padding-top` (`max(--space-sm,
--safe-top)`) after a real device (Android, punch-hole/status-bar camera)
showed the nav pill sitting flush against the status bar — `--space-sm`
alone is a fixed design-space value, not a stand-in for a status bar height
that varies per device, so it only ever cleared the status bar by
coincidence on devices where it happened to be tall enough. `.shell` still
does not apply `--safe-top` directly; `.nav-wrap` remains the one place that
carries the app's top clearance, same as before, just now actually reading
the safe-area inset instead of a token that had no callers.

`.wordmark::before` declares `content: "▮"` plainly and then upgrades to the
alt-text form `content: "▮" / ""` under `@supports (content: "x" / "")`. The alt
form is a single indivisible value, so an engine that cannot parse it (Safari
below 17.4) drops the **whole** declaration and the accent mark vanishes from
every nav in the app. Do not collapse this back into one rule.

## Known issues

**Phase 1 editorial (2026-11-01):**

- **Capacitor `SystemBars style: "DARK"` was left as-is** (out of Phase 1 scope). On the now-light paper it likely gives light status-bar icons on a light bar — needs an owner decision and a device check (`docs/frontend/android-live-reload.md`; agents don't run the native build).
- **Tabbing past the last More-sheet row** moves focus to the browser chrome and back, not straight to the first row. That is native `showModal()` behaviour (the page behind stays inert, measured); a hand-rolled wrap-around trap was not added.
- **App mode on a wide window** keeps the bottom dock (centred, max 30rem). Owner to confirm for installed desktop PWAs. *(Superseded in Phase 2: the dock is phone-only.)*
- ~~Privacy/Terms unreachable in installed windows wider than 37.5rem~~ — fixed 2026-11-01: those windows now show the footer (owner decision).
- **`--color-focus` now equals the accent**, so legacy hover rules that used `--color-focus` as a hover tint are visual no-ops until Phase 2 re-skins those views.
- Not verified on a physical device: Playwright/Chromium at 1280×989 and 390×844 only, where `env(safe-area-inset-*)` is 0.

**Terminal era (historical — the drawer, pill nav and `.wordmark` below no longer exist):**

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
- ~~**The nav pill sits flush against the device status bar on native
  Android.**~~ Fixed — user-reported via a screenshot on `build8`. Not caught
  by the earlier Playwright pass because Chromium emulation doesn't produce a
  nonzero `env(safe-area-inset-top)`, so it only ever showed up on a physical
  device. `--safe-top` now feeds `.nav-wrap`'s `padding-top`; see "Token
  discipline" above. Not re-verified on device by the agent that made the
  change — only reasoned from the same `max(--space-sm, --safe-X)` pattern
  already proven correct for `--safe-bottom`/`--safe-left`/`--safe-right` in
  this file. Confirm on-device that the pill now clears the status bar with
  visible breathing room, not just contact.

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
- 2026-08-16 · main session · wired `--safe-top` into `.nav-wrap`'s `padding-top` after a user screenshot on a physical Android device (`build8`) showed the nav pill sitting flush against the status bar; not caught by the earlier Playwright emulation pass since Chromium doesn't produce a nonzero `env(safe-area-inset-top)`. Not re-verified on device by this agent — only reasoned from the same `max()` pattern already used for the other three safe-area sides
- 2026-11-01 · frontend agent · editorial redesign Phase 1: two shells (web top bar + full-screen phone menu + footer / app bottom dock + More sheet) chosen by pre-paint `data-shell`; drawer, scrim and pill nav removed; sticky full-bleed bar via cqi; measured no document scroll in all 32 width×theme×shell×route combos
- 2026-11-01 · frontend agent · Phase 2: dock + More sheet phone-only (≤ 37.5rem), wider installed windows get the top bar and no footer; Analyze section is now the full-bleed scroller at ≥ 32rem (`data-frame` dropped from HomeScreen); footer reaches the bottom edge on desktop; documented the More-sheet → status-bar sync path
- 2026-11-01 · frontend agent · confirmed Privacy/Terms are already More-sheet rows (no change made); recorded the remaining gap for installed windows wider than 37.5rem as a Known issue
- 2026-11-01 · frontend agent · owner decision: installed windows wider than 37.5rem show the footer (top bar AND footer); the app-shell footer hide moved inside the ≤ 37.5rem query; Privacy/Terms known issue closed; shell table and footer text corrected
- 2026-11-01 · frontend agent (Phase 3) · History section scrolls like Analyze (full-bleed scroller from 32rem); dock clearance re-measured on History (last poster 700 / dock 764 at 390×844)
- 2026-11-01 · frontend agent (Phase 4) · every view and standalone route is now a `section.view-scroll` (scroller selector generalised, `data-frame` dropped from legal/offline); deleted `.tab-view`/`.surface`/`.pane`/`.home-center`/`.legal-doc`/`.legal-body`/`.page-title`; added `useMediaQuery`; More sheet and phone menu re-checked against MoreMobile.png / MenuWeb.png, unchanged
- 2026-11-01 · frontend agent (Phase 4, boards) · offline section is now a flex column filling the band at every width so its block centres on phones too; `NEXT_PUBLIC_APP_VERSION` added to next.config.mjs `env` (read from package.json; `agentRules: false` untouched); legal crumb bar removed per the boards
- 2026-11-01 · frontend agent (app Back link) · added `AppBackLink` (`.app-back`) above the title of API key, Releases, Privacy and Terms in the app shell only (`display:none` in the web shell; every width in the app shell); `application/backNavigation.ts` decides history.back() vs Analyze (Navigation API → `goToMainTab` history-state marker → same-origin referrer); `goToMainTab` now pushes `{ videolensInApp: true }`
- 2026-11-01 · frontend agent (Phase 5c) · tabs moved to /app (APP_PATH, isAppPath, mainTabHref); brand links to / in a browser tab and is static in the installed shell; landing at / uses the shared chrome
