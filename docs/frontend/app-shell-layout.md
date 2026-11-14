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
- `frontend/components/BottomTabBar.tsx` — the installed-app dock: Analyze, History, Account (only when sign-in is available, 2026-11-14), More. Owns the More sheet's open state.
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
  every measured height below it. The standalone routes set it for this
  reason. (`UpdateBanner` did too; since refinement 10 the update prompt is a
  top-layer `<dialog>` and takes no space in `.viewport`.)

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
History joined Analyze in Phase 3. **Phase 4 (2026-11-01) made it universal:** every view section is `<section class="view-scroll">` — Analyze, History, API key, Releases on `/`, plus `/privacy`, `/terms` and `/offline` — and the three scroller rules in `globals.css` target `.shell > section.view-scroll` instead of listing `data-view`s. `data-frame="fixed"` is no longer set by any route (its CSS remains, unused). The Terminal-era panel frame — `.tab-view`, `.surface`, `.pane`, `.home-center`, `.legal-doc`, `.legal-body`, `.page-title` — is deleted. `.col-label`/`.card-label` survive only for the dev preview harnesses. A new view: render `main.view-scroll` (a `section` until refinement 6), then a centred column (`.key-page`/`.releases`/`.legal-page` share one 43.5rem rule) with a `.view-head` (`h1.view-title` + `.view-lede`).
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
| Top bar | brand · tab links (≥ 48rem) · theme · Account button (≥ 48rem, when sign-in is offered) · hamburger (< 48rem) | ≤ 37.5rem: brand · theme only. Wider: same as web (links ≥ 48rem, hamburger between) |
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

- **Content never sits under the dock.** *(Refinement 1: the dock is now `position: sticky` in flow at the end of `.shell`, not `position: fixed`, so the shell's old bottom padding is 0 and the scroller simply ends where the dock begins.)* See "Refinement 1" below.
- **Top bar is sticky, full-bleed.** `.viewport` is `container-type: inline-size`; `.nav-wrap` and `.page-end` break out of the shell's gutter with `margin-inline: calc((100% - 100cqi) / 2)` + matching padding — full width without `100vw` (which counts the scrollbar and causes horizontal scroll).
- **More sheet** is a native modal `<dialog>` opened with `showModal()`: top layer, inert page, Escape via `cancel`, `::backdrop` click closes (dialog has no own padding, so only a backdrop click targets the element), focus returns to More on every close path. Add rows by editing `MORE_SHEET_GROUPS` — three row kinds: `tab` (in-place nav on `/`), `route` (plain `<a>`, works from `/offline`), `theme` (a System/Light/Dark radio group since refinement 4, THM-01; see "Refinement 13" for how it fits at large text).
- **Cascade-layer trap.** The responsive `@media` blocks in `globals.css` are *unlayered*, so they beat anything in `@layer components` regardless of specificity. The ≥ 48rem `.nav-links { display: flex }` is therefore written `:root:not([data-shell="app"]) .nav-links` — unscoped, it would resurrect the links in app mode. Any new unlayered responsive rule touching chrome needs the same guard.

### App-shell Back link (2026-11-01)

**Refinement 10:** Privacy and Terms now show the link in the web shell too (`<AppBackLink everywhere />`); API key and Releases stay app-only. See `legal-offline-routes.md`.

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

**Nothing stored follows the device (refinement 2, #3).** It used to be light
regardless of `prefers-color-scheme`, which made the installed app's launch
screen (OS night mode) hand off from dark to a light page. The pre-paint script
now resolves `prefers-color-scheme` when `videolens_theme` holds neither
"light" nor "dark", and keeps a `matchMedia` change listener for the life of the
document that re-reads storage first, so it acts only while nothing is stored.
A stored choice still wins. The toggle (top bar and More sheet) flips the
painted theme and **stores** the result; nothing returns to "follow the device"
short of clearing site data (a three-way System/Light/Dark control is the
follow-up if wanted). The More sheet's "Dark theme" row shows "Following your
device" under its label while nothing is stored. Still no
`@media (prefers-color-scheme)` block in the stylesheets: the script always
stamps `data-theme`. `components/theme.ts` has `SYSTEM_DARK_QUERY` and
`storedTheme()`; `DEFAULT_THEME` is gone.

The browser-chrome colour follows it. `viewport.themeColor` used to be a
`prefers-color-scheme` **pair**, which was right only while the app tracked the
OS; a dark-OS visitor would now get a dark strip above a light page. It is one
media-less tag carrying the light value, which the pre-paint script and
`toggleTheme` both re-point at whatever theme is actually in use.

**Status-bar icon style vs WebView version (refinement 2, #2).**
`infrastructure/systemBars.ts` reads the WebView major from the user agent
(`Chrome/NNN`). On **140+** the page paints under the bars, so the style
follows the app theme (Light/Dark). Below **140** the bars show the OS-themed
window background, so it sends `SystemBarsStyle.Default`, which the native side
resolves from the OS night mode at call time. `useSystemBarsTheme` re-sends it
on a `prefers-color-scheme` change and on return to the foreground, because
the activity handles `uiMode` itself and the resolved style would otherwise go
stale. An unreadable UA counts as modern. `capacitor.config.ts`
`SystemBars.style` is now `"DEFAULT"` (was `"LIGHT"`); it reaches the APK on
the next `cap sync`. This targets NAV-07 (white clock on a white bar, system
light + app dark, WebView 124). The bar background on < 140 is unchanged: it
follows the OS, and now so do the icons.

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

## Refinement 1 (2026-11-01)

**Dock pinned (#1).** The dock was `position: fixed`, but `.viewport` is
`container-type: inline-size`, and containment makes it the containing block
for fixed descendants. In the installed app (where `.viewport` is the phone
scroller) the "fixed" dock therefore scrolled away with the content, on the
intake and on the result view. It is now `position: sticky; bottom:
max(var(--space-sm), var(--safe-bottom))` with `margin: auto auto <same>`, the
last flex item of `.shell`. Measured at 390×844 app shell, light and dark:
dock 764–828 before and after scrolling the intake, the progress view and the
result to the bottom; the terms checkbox, Retry and "Analyze another file" are
all hit-testable (nothing over them).

**Keyboard (#2).** `application/useSoftKeyboard.ts` (mounted once in
`BottomTabBar`) stamps `<html data-keyboard="open">` while a text field has
focus on a coarse pointer, and clears it on blur or when the viewport grows
back after having shrunk (the back gesture dropping the keyboard with focus
kept); a shrink with focus kept re-opens it. On open the field is scrolled to
the centre after 300 ms. `:root[data-shell="app"][data-keyboard="open"] .tabbar
{ display: none }`. No `@capacitor/keyboard` (not installed; no native plugins
added). Measured: focus → flag + dock hidden; shrink → open; grow back → closed;
shrink again over the same focused field → open; blur → closed; desktop
(fine pointer) never flags.

**Hardware back, Android only (#4).** `domain/ports.ts` `NativeShell` →
`infrastructure/nativeShell.ts` (`@capacitor/app` `backButton` listener,
`exitApp`) → `container.nativeShell` → `application/useHardwareBack.ts`
(mounted in `BottomTabBar`) → pure `decideBack()` in `backNavigation.ts`:
open dialog → close it (cancelable `cancel` first, so Welcome records its
dismissal); WebView `canGoBack` → `history.back()`; not on Analyze → Analyze;
on Analyze → exit. On the native shell `goToMainTab` **replaces** the entry
(fresh state object; the `videolensInApp` marker carried over only if present);
`handleOpenRun` passes `{ push: true }` so back from an opened run returns to
History. Browser/PWA keep the push behaviour and their own back. `AppBackLink`
/ `hasInAppPrevious` unchanged. Verified: `decideBack` 6/6 unit cases (node);
emulated bridge (fake `PluginHeaders` + `nativeCallback`): three tab taps add 0
entries; back with the More sheet open closes it; back on History → `/app`;
back on Analyze calls `App.exitApp`; opening a run from History adds 1 entry
and back returns to `?view=history`.

**Phase scroll (#6).** `HomeScreen` resets the Analyze section and `.viewport`
to `scrollTop = 0` in a layout effect whenever the run phase (intake →
progress → result / failed) changes. Measured: progress, result and failed all
start at 0 after submitting from a scrolled intake.

**Scrollbar gutter (#8).** `scrollbar-gutter: stable` on the real scroller,
only for `(hover: hover) and (pointer: fine)`: `.viewport` below 32rem, the
`.shell > main.view-scroll` band from 32rem up (where `.viewport` is
`auto`). Touch devices (overlay scrollbars) get no empty gutter. The
`::-webkit-scrollbar` styling is under the same media query. Measured at 1366
(classic scrollbars): Analyze, History and API key bands are all 1351px wide,
brand and heading edges identical between Analyze and History; at 390 the
gutter is `auto` and the band is the full 390.

**Landscape phone (#10).** The app-shell block is now `@media (max-width:
37.5rem), (max-height: 31.25rem)`, so a short installed window keeps the dock;
under `max-height: 31.25rem` the top bar drops its links and is 56px. Measured
844×390 app shell: nav 56, band 57–310, dock 310–374, terms reachable. A tall
tablet (1024×1366 app shell) keeps the top bar and footer, no dock.

**Landscape phone (refinement 2, #7).** Under `max-height: 31.25rem` in the
app shell the dock goes one row (icon beside label), 52px tall with 44px
targets, lifted 8px, with an 8px gap above it so the scroller visibly ends
before the dock; the intake headline drops to 2.25rem (one line at 844px).
Measured 844x390: dock 330-382, headline 215-253 (was 215-323 against a dock
at 310). The More sheet lays its two groups side by side under the title
(max-width 44rem) and fits in 237px with no scroll (was 381px of content
clipped to 342). Same at 915x412; light and dark checked.

## Refinement 3 (2026-11-02)

**Nothing under the dock, at rest or scrolled (#2).** android-66 found
"Retry now" under the dock on the Connection lost screen (portrait phone); a
tap on it hit History. Cause: below 32rem the phone app shell still scrolled
`.viewport` as a whole with the dock `position: sticky` at its bottom, and
sticky overlays: refinement 1's "the scroller ends where the dock begins" was
only true at the *end* of the scroll. Fix (unlayered, `@media (width < 32rem)`,
app shell only): the same measured frame as 32rem and up. `.shell` is one
viewport (`flex: 1; min-height: 0`), the active `main.view-scroll` is the
only scroller (`overflow-y: auto`), and the dock ends the column below it with
an 8px gap (`margin-top: var(--space-2xs)`, as in landscape). The web shell
keeps page scroll. Also `position: relative` on `.shell > main.view-scroll`:
Tailwind `.sr-only` spans (API key's "opens in a new tab") were absolutely
positioned against `.viewport`, escaped the section's clipping and gave the
whole frame ~320px of scroll on API key in landscape and at 360x640 (nav and
dock rode up).
Measured (Playwright, `next start`, light + dark, 390x844 / 360x640 / 844x390 /
915x412): section bottom 8px above the dock top on intake, progress, Connection
lost, failed, expired, History, API key, Releases and Privacy; zero
interactive elements visible under the dock; `.viewport` never scrolls;
"Retry now" is either fully above the dock or clipped below the fold and
reachable by scrolling, where `elementFromPoint` hits the button.

**Pre-paint scripts (#9). All four (theme, shell, landing redirect, splash)
are one inline script in the root layout `<head>`; see `landing-page.md`.

**Status bar / nav strip in dark (#3), not fixed (lead decision: no native
plugin).** The JS side is right (`SystemBars.setStyle` Dark/Light per
`data-theme`, guarded). The white comes from native: Capacitor's `SystemBars`
lets the page paint under the bars only on **WebView ≥ 140** with
`viewport-fit=cover`; on older WebViews it pads the WebView and the bars show
the decor view's background (`windowBackground`, white), and `setStyle` resets
that background on every call. **Old WebViews (<140) show a white bar; WebView
140+ is fine.** Android System WebView updates through Play. The emulator here
reports WebView 124. Native diff, **not applied**:

```java
// android/app/src/main/java/ai/videolens/app/AppWindowPlugin.java
@CapacitorPlugin(name = "AppWindow")
public class AppWindowPlugin extends Plugin {
  private Integer color;
  @PluginMethod public void setBackgroundColor(PluginCall call) {
    color = Color.parseColor(call.getString("color", "#F6F4EE"));
    getActivity().runOnUiThread(this::apply); call.resolve();
  }
  @Override protected void handleOnConfigurationChanged(Configuration c) { apply(); }
  private void apply() { if (color != null) getActivity().getWindow().getDecorView().setBackgroundColor(color); }
}
// MainActivity.onCreate, before super.onCreate(savedInstanceState):
registerPlugin(AppWindowPlugin.class);
```

…called from `CapacitorSystemBarsStyler.matchTheme` **after** `SystemBars.setStyle`
with `THEME_COLOR[theme]`.

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
- **The `--z-*` scale is aspirational.** Only `--z-banner` had a caller
  (`UpdateBanner`, removed in refinement 10; now none); `globals.css` improvises `1/3/4/5/10` inline and none of
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

- **The web footer wraps at 320 px from ~140% text** (refinement 13). "VideoLens
  AI", Privacy and Terms need ~287px of a 272px row at 320/150%; keeping one
  line would mean dropping the name or shrinking text below the user's scale.
  Its spacing is capped instead (146 → 100px tall at 150%, 195 → 119px at
  200%), see "Refinement 13". One line at 360/150% and at every width ≤ 130%.

## Refinement 4 (2026-11-02)

**Keyboard reveal (INT-01, INT-05).** `useSoftKeyboard` used to call
`field.scrollIntoView({ block: "center", behavior: "smooth" })` once, 300ms
after focus. Two ways that leaves the field under the keyboard: the
keyboard's resize lands after the timer (a slow WebView; android-66 saw it in
landscape, with only the top "Limited: link downloads" note visible), or the
smooth scroll is cut short by that resize. Now:

- `revealField(field)` (exported from `application/useSoftKeyboard.ts`) is
  instant, reveals the field's `[data-reveal-group]` ancestor (field plus its
  error message) when that fits, measures against the **visual** viewport, and
  nudges the nearest scroller by whatever is still hidden. A no-op when the
  target is already fully visible.
- It runs after the 300ms settle **and** again (next frame) whenever the hook
  measures the shrink, so a late keyboard re-reveals.
- Simulated in headless Chromium at 844x390 app shell: focus the field from
  scrollTop 0, shrink the WebView to 190px 450ms later (after the timer) and
  30ms later: field at 113-165 of 190 in both cases, dock hidden. Not measured
  on a device; INT-05 is android-66's retest.

**Theme: System / Light / Dark (THM-01).** The More sheet's "Dark theme"
switch is replaced by a three-way segmented radio group (`fieldset.theme-choice`,
`.segmented`, 44px segments, native radios so arrows, the single tab stop and
the group name come from the platform). `components/theme.ts` gained
`ThemePreference`, `themePreference()`, `deviceTheme()`, `paintTheme()` and
`setThemePreference()`; "system" removes `videolens_theme`, after which the
head script's existing `prefers-color-scheme` listener (it re-reads storage on
every change) follows the device again. The head script itself is unchanged.
The header toggle stays two-way and now calls `setThemePreference` too. The
sublabel reads "Following your device" on System and "Set in this app"
otherwise. Verified: dark OS gives System checked and dark; Light ignores an OS
flip; ArrowRight goes Light to Dark; System clears storage and follows the OS
live both ways; the header toggle stores a choice and More's System gives it
back; meta theme-color follows. *(Refinement 13: the segments now carry side
padding and re-lay themselves at large text — indent dropped, then stacked —
via container queries on the fieldset; see "Refinement 13".)*

## Refinement 5 (2026-11-02)

**Keyboard reveal clipped to the section (INT-01b).** `revealField` now
treats the field's scrolling section (below the fixed header) as the visible
band, and prefers field + error message over the group with Analyze when the
band is short; see `upload-form.md`.

**Native theme follows the app's choice (THM-01b).** The choice made in More
(or the header toggle) is mirrored natively: `components/theme.ts`
`setThemePreference` notifies `themePreferenceSource` listeners *before*
painting; `application/useSystemBarsTheme.ts` (now takes that source, mounted
by `ThemeToggle`) calls `nativeThemeMirror.setPreference`
(`infrastructure/nativeTheme.ts`, port `NativeThemeMirror` in `domain/ports.ts`)
once on mount and on every change. The adapter is Android-only and calls the
app module's own Capacitor plugin `NativeThemePlugin` (registered in
`MainActivity`), which stores the choice in SharedPreferences
(`videolens_native_theme`/`preference`) and applies
`AppCompatDelegate.setDefaultNightMode` live, plus
`UiModeManager.setApplicationNightMode` on API 31+ (system-persisted; the
launch screen uses it). `MainActivity.attachBaseContext` applies the stored mode
before AppCompat resolves the configuration, so window background, the
night-qualified colours and SystemBars' `DEFAULT` all start on the app's
choice. A live change does not recreate the activity: `uiMode` is in
`configChanges`, and AppCompat 1.7.1 (`updateAppConfiguration`, checked by
disassembly) then calls `onConfigurationChanged` instead. When the native mode
changed, the hook re-resolves DEFAULT bars (WebView < 140) and, for System,
repaints from the device. The bridge call is sent before the bar restyle on
purpose. Device behaviour is android-66's to verify.

## Refinement 6 (2026-11-02)

**A11-02, one `<main>` per page.** The view band is now `<main
class="view-scroll" data-view="…">` instead of `<section>` on every route
(HomeScreen's views, the landing page, `LegalShell` for /privacy and /terms,
/offline, and the new 404). Only one view renders at a time, so each page has
exactly one `main` landmark. Every selector that named the band
(`.shell > section.view-scroll`, `.shell > section[data-view…]`,
`~ section[data-view]`) in `globals.css` and `landing.css` now names `main`;
nothing else changed in the frame. Checked at 390x844 and 1366x768, light and
dark, web and installed shells, on /, /app (all four views), /privacy, /terms,
/offline and an unknown path: one `main`, nav present, footer (web) or dock
(installed), no horizontal scroll, and the band is the scroller wherever it was
before (the web shell below 32rem keeps page scroll, as designed).

**A11-13, footer links.** Measured, not changed: `.foot-legal a` are already
44px tall (`min-height: 2.75rem`) at 390 and 1366.

## Refinement 7 (2026-11-02)

**THM-01b-6, System stays dark after the OS goes light.** Repro (android-66,
API 35, WebView 124, intermittent): OS dark, Light stored, cold launch (the
activity starts forced `MODE_NIGHT_NO`), More > System, then `cmd uimode night
no`. Bars went light, the page stayed dark: in the WebView
`matchMedia('(prefers-color-scheme: dark)')` stayed true until a cold relaunch.
Chromium derives that media feature from the WebView's (activity) context,
which was built under the forced override; after the override is lifted it no
longer tracks the real system `uiMode`. The native side was right (the bars
followed), only the WebView's media query was stale.

Fix: under System, in the installed app, the page no longer trusts the media
query for the OS state.

- `NativeThemePlugin.systemNight()` reads the OS state:
  `UiModeManager.getNightMode()` YES/NO first (the user-wide setting; never
  this app's override, since AppCompat overrides only the activity
  configuration and `setApplicationNightMode` is stored per package); for
  AUTO/CUSTOM (schedules) or with Battery Saver on (which forces dark without
  touching that setting) it falls back to the night bit of
  `Resources.getSystem().getConfiguration()`, the process configuration. That
  includes the per-package override on API 31+, but it is only consulted
  under System, and choosing System clears that override.
- Exposed as `getSystemNight()` → `{ dark }` and a `systemNightChanged`
  `{ dark }` event, sent from the plugin's own `handleOnConfigurationChanged`
  (BridgeActivity forwards `MainActivity.onConfigurationChanged` to every
  plugin), `handleOnResume`, and after `setPreference` changes the mode; only
  when the value differs from the last one sent.
- Port `NativeThemeMirror` gains `systemNight()` and `onSystemNightChange()`
  (`infrastructure/nativeTheme.ts`; null / no-op off Android or on an older
  APK). `useSystemBarsTheme` asks on mount and on `visibilitychange`, listens
  for the event, and hands the value to `themePreferenceSource
  .adoptDeviceTheme`, which makes it what `deviceTheme()` returns from then on
  and repaints when nothing is stored. It also re-resolves DEFAULT bars on
  WebView < 140.
- The head script's `prefers-color-scheme` listener (`app/layout.tsx`) stands
  down once `window.__videolensNativeScheme` (`NATIVE_SCHEME_FLAG` in
  `components/theme.ts`) is set, so a stale media query cannot repaint over the
  native value. First paint still uses the media query (correct on a cold
  launch). The browser is unchanged: no native value, matchMedia as before.

Rejected: re-applying `setDefaultNightMode(FOLLOW_SYSTEM)` on the
configuration change. AppCompat returns early when the mode is unchanged, and
its own `onConfigurationChanged` already re-runs `applyDayNight`, which is why
the bars were right; neither reaches Chromium's media-query state, which is the
part that was wrong. Recreating the activity would fix the WebView but loses
page state, which is what `configChanges uiMode` exists to avoid.

**Capacitor's "Error injecting safe area CSS" on launch: left, harmless.**
Emitted by Capacitor 8's own `SystemBars` plugin
(`com/getcapacitor/plugin/SystemBars.java`, `injectSafeAreaCSS`). On API 35+
`load()` calls `initSafeAreaCSSVariables()`, which runs
`document.documentElement.style.setProperty('--safe-area-inset-*')` through
`evaluateJavascript` while the bridge is still being built, before the first
page has a document, so `documentElement` is null and its try/catch logs the
error. The same injection re-runs from the insets listener after
`onPageCommitVisible` / `onDOMReady` and succeeds. No clean fix: it runs inside
plugin `load()`, before any of our code; the only config switch,
`insetsHandling: "disable"`, also removes the insets listener that pads the
WebView below the bars on WebView < 140 (the API 35 emulator ships 124).
The app does not read the `--safe-area-inset-*` variables (it uses
`env(safe-area-inset-*)`), so nothing visible depends on the failed call.

## Refinement 8 (2026-11-02)

**"Unable to open asset URL: /app/__next.app.__PAGE__.txt?_rsc=…" in logcat.**
This was a real miss, not just noise, and only for APKs built on Windows.

- *What it is.* With `output: "export"` the App Router prefetches each route
  segment from a flat file beside the route: the client asks for
  `/app/__next.app.__PAGE__.txt` (segment path `/app/__PAGE__`, `/` turned into
  `.`, in `next/dist/shared/lib/segment-cache/segment-value-encoding.js`).
- *Why it failed.* Next 16.4's exporter (`next/dist/export/index.js`,
  `collectSegmentPaths`) lists segment files with `path.relative`, which gives
  `app\__PAGE__…` on Windows. Only `/` is replaced, and `path.join` then reads
  the backslash as a separator, so a Windows build wrote
  `out/app/__next.app/__PAGE__.txt` (a directory) instead of the flat file. The
  asset server has nothing at the requested path; the name has a `.`, so it
  does not fall back to `index.html` either, and answers an empty 404, logging
  the line above. Every route's `__PAGE__` segment was affected (`/app`,
  `/privacy`, `/terms`, `/offline`, `/_not-found`); `_tree`, `_index` and
  `_full` are flat already. Linux builds (CI's release APK, `ubuntu-latest`)
  write the flat name and never had this.
- *What it cost.* Only the prefetch. Measured over an emulated asset server
  (prefetch 404s, no bridge change): tapping History in the dock on
  `/privacy.html` stayed a client-side navigation (same document, no document
  request) and fetched the full `/app.txt` payload instead, so the tap waited
  on one extra request. No full reload, no flash.
- *Fix.* `scripts/fix-export-segments.mjs`, run by `build:mobile` between
  `next build` and `build-sw.mjs`: every file under a directory named
  `__next.<…>` in `out/` moves to the flat name the client builds, and the
  directory goes. A no-op where the names are already flat (Linux, macOS, or a
  second run). After it, the same test shows the `__PAGE__` prefetch answered
  200 and the dock tap needs no further request. `trailingSlash`, the export
  layout and the `.html` hop are untouched. Drop the script once Next fixes
  the exporter (check for a `__next.*` directory in `out/` after a Windows
  build).

## Refinement 13 (2026-11-02)

Large-text fixes in the chrome. One rule of thumb now governs the bar and the
footer: **text may scale; chrome spacing and targets are capped** with
`min(<old rem>, <px>)`. Each cap equals the old rem value at 100% root font,
so normal scale is pixel-identical (measured at 390 and 1280, light and dark,
on /app, /privacy and results, against the old rules re-injected).

**Top bar (D-R12-1).** Menu was already an icon-only button (`aria-label`
"Menu"); it was clipped because *everything* in the bar grew with rem — at
320 px / 150% the 28.5px wordmark, two 66px buttons and 24px gaps needed 361px
of a 272px row (Menu 41px off-screen; 161px off at 200%). Now:

- `.theme-toggle` / `.menu-toggle` are a fixed 44px with 18px glyphs — a
  target gets no easier to hit past 44px.
- The wordmark is a logotype, so it stops growing at 22px
  (`min(1.1875rem, 22px)`; 24px from 48rem), mark `min(1.625rem, 30px)`.
- Gaps `min(var(--space-sm), 16px)` / `min(0.5rem, 8px)` (8px between the two
  buttons, the touch-spacing minimum).
- `.nav` min-height `min(4.25rem, 68px)` (and `min(4.75rem, 76px)` from 48rem,
  `min(3.5rem, 56px)` in the landscape app bar). At 150% the bar was 103px
  tall and at 200% 137px; it is 69px at every size now, which goes straight
  back to the content band.

No breakpoint, nothing reads the width; the theme toggle stays in the bar.
Result at 320 / 200%: brand 32–161, theme 192–236, Menu 244–288 (32px
gutter); at 360 / 200%: theme 232–276, Menu 284–328. The bar is the same component
on every route, so the fix is too. The installed app's bar (wordmark + theme,
no Menu) uses the same rules and fits at 320/360/390 × 100–200%.

**Footer (the ~330px band observation).** It cannot stay on one line at
320 / 150%: "VideoLens AI" plus Privacy and Terms need ~287px of 272 even with
tightened gaps, and dropping the name would lose content. So it still wraps
there (one line at 360/150% and everywhere at ≤ 130%), but its spacing no
longer grows: `.foot` gap `0 min(var(--space-sm), 16px)` (no row gap — the
links' own 44px height spaces the two lines), min-height `min(3.5rem, 56px)`,
`.foot-legal` gap `min(var(--space-md), 24px)`, links a fixed 44px tall.
Measured at 320×640 (headless Chromium, root font emulated): footer 146px →
100px at 150%, 195px → 119px at 200%; with the 69px bar the visible band
between bar and footer goes from ~390px to ~470px at 150% and ~308px to
~452px at 200%. The device number (~330px at 150%) was taken from a taller
bar/footer under Android's text scaling, so expect a similar ~80px gain there;
not yet re-measured on the device.

**More sheet theme control.** `.theme-choice` is a size container
(`container: theme-choice / inline-size`, font-size 1rem), and the segmented
control reads its room in **em**, so the switch points move with the text,
not the viewport:

- segments carry `padding-inline: 0.375rem` and `min-width: 0`;
- `@container theme-choice (width < 16em)` drops the 3.375rem indent (the
  track spans the full width under the icon + label);
- `@container theme-choice (width < 12.75em)` stacks the three segments, one
  full-width 44px row each, inside a 3px-padded `--radius-control` track.

"System" measures 3.06em in Chromium and 3.04em on the device (73px at
24px), so the thresholds leave ~0.3–0.45em of slack on both. Measured (headless,
320/360/390 × 100–200%, light and dark): indented row at 320/100% (as before),
full-width row at 320/115–130%, stacked at 320/150–200% and 360/150–200%;
every label at least 4px inside its segment, every segment ≥ 44px, nothing
past the sheet. Android's text zoom may scale font sizes more than rem lengths
(R12 hypothesis); the em queries follow the text either way.

Verified in `scratchpad\refine13\verify.py` (499/499, no page errors).

## Refinement 14 (2026-11-02)

**The refinement 13 caps now hold in the installed Android app.** Device QA
(run 15) showed that neither the `min(rem, px)` caps nor the em container
queries worked on Android. The cause was the WebView's text zoom, which
multiplies font sizes after layout has resolved them. At font 2.0 the wordmark
rendered at 38px, the theme control stayed one indented row, and "System"
overflowed its segment by up to 33px.

The CSS is unchanged. Android now delivers the system font scale the way a
browser's text-size setting does, as the root font-size, with text zoom pinned
to 100. See "Refinement 14" in `android-update-check.md` for the native side:
`FontScalePlugin`, a document-start script, and `application/nativeFontScale.ts`
in the pre-paint head script. One model, so the web, the harness and the
device now agree.

**Measured** in `scratchpad\refine14\verify.py`. The plugin's exact script is
emulated, both with `<html>` present at document start and without it.
- **Text size.** Root and body are 16, 18.4, 20.8, 24 and 32px at 1.0, 1.15,
  1.3, 1.5 and 2.0. That holds after hydration, after a client tab switch, and
  on a fresh document (`/privacy`).
- **Native header** at 320, 360 and 390, light and dark. The wordmark is
  19 / 21.85 / 22 / 22 / 22px, the toggle is 44px and the bar is 68px. At
  320 / 2.0 the brand sits at 32–161 and the toggle at 244–288.
- **Landscape bar** at 915×360 and 844×390. It is 56px at every scale (run 15
  measured 63px at 2.0). These widths are past 48rem, so the wordmark cap
  there is 24px (21px at 1.0).
- **Theme control.**

  | | 1.0 | 1.15 | 1.3 | 1.5 | 2.0 |
  |---|---|---|---|---|---|
  | 320 | indented row | full-width row | full-width row | stacked | stacked |
  | 360 | indented row | indented row | full-width row | stacked | stacked |
  | 390 | indented row | indented row | indented row | full-width row | stacked |

  Wherever it stays a row, "System" has at least 10px of clear space each
  side. So the 6px label padding refinement 13 added is kept: it only made
  things worse while the queries never fired.
- **Live change.** 1.0 → 2.0 → 1.3 → 1.0 with the sheet open, using the same
  script and no reload: the root follows, the control re-lays out, and the
  inline size clears at 1.0.
- **Web.** No inline root size. The browser's own setting stays the root
  (16px, or 24px under an emulated 150%).
- **Refinement 13 web regression.** `scratchpad\refine14\r13_regress.py` is
  the refinement 13 harness re-run against this build.

Still for the device:
- run 15 re-measured on `refine14-debug.apk`;
- no visible size jump on a cold launch;
- a live font change with a result open.

The footer is hidden in the app shell, so it has nothing to re-check there.

## Refinement 15 (2026-11-02)

Device round 16 (after refinement 14 made the Android font scale the root
font-size) found three large-text problems. All three are fixed in
`app/globals.css` only, and every change equals the old value at 100%, so
normal scale is pixel-identical (measured).

**Dock.** It was the one piece of chrome refinement 13 did not cap: 64 → 128px
portrait and 52 → 104px sideways at 200%, leaving a 167px content band on a
740×360 screen. It now follows the refinement 13 rule. Height, padding, gaps,
margins and icons are `min(<old rem>, <px at 100%>)`, items have a fixed 44px
floor, and labels may grow from 12 to 14px (portrait) or 13 to 15px
(sideways) and stop there. The dock is now **64px portrait and 52px sideways
at every text size**. Stopping the labels is a deliberate trade, the same one
refinement 13 made for the wordmark. Four labels do not fit a 320px dock past
~14px, and a dock that doubles in height takes the room the text needs.

**More sheet rows.** At 320/200% the icon tile, the gap and the chevron grew
with the text and squeezed the label below its one word: "Releases" ran 39px
into its chevron, "Privacy" 17px. The tile is now capped at 40px (icon 18px),
the gap at 14px and the chevron at 18px (`flex: none`). The label keeps
`min-width: 0` and takes the rest, so it may wrap between words but no longer
reaches the chevron. The theme row's head uses the same tile and gap, so the
icon and label columns stay straight. Its segmented-control indent is now
`calc(min(2.5rem, 40px) + min(0.875rem, 14px))`, which is 3.375rem at 100%.
The sheet padding and the rows' inline padding stay in rem. That keeps
`.theme-choice`'s content box, which the refinement 13 container queries
measure, unchanged, so **every theme tier is unchanged**. Where the indented
row survives above 100% (390 and 412 at 130%), the indent is 63px instead of
79px, so the three segments are 16px wider. In the stacked tiers the segments
sit up to 48px higher, because the head's tile is 40px rather than 80px.

**Intake cards.** See `capability-reporting.md` ("Large text") and
`free-runs.md` (UI). Both cards stack when the sentence would otherwise get
under ~9em, using em container queries (`cap-notice` < 15em, `free-runs` <
17em).

**Measured** with `scratchpad\refine15\verify.py`: 640/640 checks, with no
page errors. It runs on the static `out/` export of this build, side by side
with the 04b5946 export, at 320/360/390/412 × 100/130/150/200%, light and
dark. `verify_reach.py` covers the reachability notice (32/32).

| | 100% | 130% | 150% | 200% |
|---|---|---|---|---|
| Dock portrait (all widths), old → new | 64 → 64 | 83 → 64 | 96 → 64 | 128 → 64 |
| Dock 740×360, old → new (band) | 52 → 52 (235) | 68 → 52 (215 → 235) | 78 → 52 (201 → 235) | 104 → 52 (167 → 235) |
| Capabilities notice stacks at | — | 320, 360 | all four | all four |
| Free-runs strip stacks at | — | 320, 360, 390 | all four | all four |
| Sheet: smallest label→chevron gap at 320, old → new | 140 → 140 | 87 → 108 | 51 → 87 | **−39 → 33** |

- **Header.** Native and web header boxes are identical to the baseline at
  every width, scale and scheme.
- **Words.** No word in any card is split across lines in either shell, with
  the "Limited: link downloads." sentence, a three-capability sentence, the
  spent free-runs sentence and the unreachable notice.
- **Layout.** Nothing is clipped and there is no horizontal page scroll. Every
  target is at least 44px. Dock labels sit inside their items.
- **Not done:** `.cap-toggle` and `.btn` still reach 88px tall at 200%, from
  the coarse-pointer `2.75rem` floor. Sheet rows still keep their `3.5rem`
  min-height. Both are outside this pass.

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
- 2026-11-01 · frontend agent (refinement 1) · dock sticky in flow (containment had captured the fixed dock), keyboard hides dock, Android hardware back (NativeShell port, decideBack, native tab switches replace), phase scroll-to-top, scrollbar-gutter on the real scroller (fine pointers only), landscape keeps the dock, #3 native diff documented not applied
- 2026-11-02 · frontend agent (refinement 2) · default theme follows the device live (stored choice wins; sheet shows "Following your device"); system-bar style from the OS on WebView < 140 (Default, re-sent on OS flip/resume), app theme on 140+; capacitor SystemBars style DEFAULT; landscape: one-row 52px dock, one-line headline, two-column More sheet
- 2026-11-02 · frontend agent (refinement 3) · phone app shell (< 32rem) uses the measured frame (section scrolls, dock below it, 8px gap) so nothing sits under the dock at rest; scroll sections are the containing block for `.sr-only`
- 2026-11-02 · frontend agent (refinement 4) · keyboard reveal now group-aware, instant, visual-viewport aware and repeated on the measured shrink (INT-05); More sheet theme switch replaced by System/Light/Dark radios backed by theme.ts setThemePreference (THM-01)
- 2026-11-02 · frontend agent (refinement 5) · theme choice mirrored natively (NativeThemePlugin + infrastructure/nativeTheme.ts, AppCompat night mode at attachBaseContext and live, UiModeManager on API 31+) so launch/window/bars follow the app, not the OS (THM-01b); revealField clipped to the scrolling section (INT-01b)
- 2026-11-02 · frontend agent (refinement 6) · A11-02 view band is <main> on every route (one landmark per page); footer link height measured at 44px
- 2026-11-02 · frontend agent (refinement 7) · THM-01b-6: System paints from the native OS night state (NativeThemePlugin getSystemNight + systemNightChanged; theme.ts adoptDeviceTheme; head-script listener stands down) instead of the WebView's stale prefers-color-scheme; documented the harmless Capacitor "Error injecting safe area CSS" launch log
- 2026-11-02 · frontend agent (refinement 8) · RSC segment prefetch 404s in the APK traced to a Next 16.4 Windows-only export bug (nested `__next.app/__PAGE__.txt`); `scripts/fix-export-segments.mjs` flattens them in `build:mobile`; cost was one extra `/app.txt` fetch per navigation, never a full reload
- 2026-11-02 · frontend agent (refinement 10) · UpdateBanner references updated (now a top-layer dialog, no `.viewport` space); Privacy/Terms Back link shows on the web too; `html, body` min-width is 320px, not 20rem
- 2026-11-02 · frontend agent (refinement 13) · D-R12-1: top bar capped with `min(rem, px)` (44px icon buttons, 22px wordmark cap, 68px bar), fits at 320/360 × 100–200% on every route, normal scale identical; footer still wraps at 320/150% but its gaps/heights are capped (146 → 100px); More sheet theme control re-lays via em container queries (indent dropped, then stacked) with padded labels
- 2026-11-02 · frontend agent (refinement 14) · no CSS change: Android now sets the system font scale as the root font-size (text zoom pinned to 100, see android-update-check.md), so the R13 caps and theme-control container queries work in the app; measured wordmark ≤ 22px, landscape bar 56px and the theme tiers at 320/360/390 × 1.0–2.0; repaired the mangled R13 harness path
- 2026-11-02 · frontend (refinement 15) · dock capped with min(rem, px) (64px portrait / 52px sideways at every scale, labels ≤ 14/15px, 44px items); More-sheet icon tile, gap and chevron capped so labels never reach their chevrons (320/200% "Releases" −39 → +33px), theme indent follows; theme tiers and header unchanged; intake cards stack (see capability-reporting.md, free-runs.md)
- 2026-11-08 · frontend subagent (auth phase 2) · new `account` tab (`MAIN_TABS`, `TAB_LABEL`, a More-sheet row with `CircleUserRound`), shown only when sign-in is configured and the `auth` capability is `ok` (`navTabs(showAccount)`); `/app?view=account` still renders the panel. See auth-sign-in.md
- 2026-11-13 · frontend agent · top bar gains `.nav-account` (round Account link after the theme toggle, ≥ 48rem only, same visibility rules as `.nav-links`); Account leaves the inline text tabs. See auth-sign-in.md
- 2026-11-14 · frontend agent · dock gains an Account item (4 items when `showAccount`, 62px each at 320, 52px tall, labels unclipped); the More sheet drops its Account row. See auth-sign-in.md
