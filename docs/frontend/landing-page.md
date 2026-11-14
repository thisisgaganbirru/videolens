# Landing page and the `/app` route (Phase 5c)

The tool moved from `/` to `/app`. `/` is now a landing page for people who
arrive from a browser. The installed app (PWA standalone or Capacitor) never
shows it: it goes straight to `/app`.

Boards: `design/shots/Landing.png` (phone, 390) and `LandingWeb.png` (desktop, 1280).

## Files

| File | Role |
|---|---|
| `frontend/app/page.tsx` | `/`: inlines `LANDING_REDIRECT_SCRIPT`, then `<LandingScreen />`; imports `landing.css` |
| `frontend/app/app/page.tsx` | `/app`: the tool (Suspense, fallback `<HomeScreen activeTab="analyze" />`, then `<RoutedHomeScreen />`), plus the 5d splash and Welcome (see `first-run.md`) |
| `frontend/components/LandingScreen.tsx` | Server component: hero, sample card, How it works, What you get, closing band, footer, dock |
| `frontend/components/SampleResult.tsx` | Client: the sample results card with working ARIA tabs (TL;DR, Notes, Transcript, On-screen) |
| `frontend/components/LandingAllowance.tsx` | Client: the two allowance lines under the hero actions (fallback prerendered; server numbers after the reads) |
| `frontend/application/accountAllowance.ts` | `ACCOUNT_FREE_RUNS_PER_MONTH` (plain module, readable from the server-component landing) |
| `frontend/app/landing.css` | Landing-only styles, unlayered; `:root[data-redirecting] body { visibility: hidden }` |
| `frontend/application/landingRedirect.ts` | `LANDING_REDIRECT_SCRIPT` (inline, blocking) and `TOOL_QUERY_PARAMS` |
| `frontend/application/useMainTab.ts` | `APP_PATH = "/app"`, `isAppPath()`, `mainTabHref(tab, base)`; `goToMainTab` pushes onto `/app` |
| `frontend/components/AppNav.tsx` | Brand is a `<Link href="/">` in a browser tab, a static `<span>` in the installed shell (CSS picks one); `landing` prop |
| `frontend/app/tokens.css` | `--color-band` / `--color-band-ink` for the closing band |

## Redirects on `/` (before paint)

`LANDING_REDIRECT_SCRIPT` runs inline in the **root layout's `<head>`**
(`app/layout.tsx`, concatenated after the theme and shell scripts), before
anything paints. Until refinement 1 it was rendered by the landing page itself;
a client-side navigation to `/` then made React re-create the `<script>`, which
never runs and logs "Encountered a script tag while rendering React component".
The head is only hydrated, never re-created, so the script now gates itself on
the path instead. The `data-redirecting` hide rule moved from `landing.css` to
`globals.css` for the same reason (it must apply on any document). It sets `<html data-redirecting>` (which hides the body)
and calls `location.replace()`, so no history entry is left behind:

| Arrives at | Goes to | Why |
|---|---|---|
| `/?view=X` (old tab URLs, old bookmarks, old shortcuts) | `/app?view=X` | The tabs live on `/app` now |
| `/?share-target=1&…`, `/?url=…`, `/?text=…`, `/?title=…` | `/app` + the same query | Share links from older installs, which still have the old `share_target.action` |
| `/` in the installed shell (`data-shell="app"` or Capacitor native) | `/app` + the same query | The installed app is the tool, not a website |
| `/` in a browser | stays, shows the landing | |

The installed check is repeated once at `DOMContentLoaded`, because the shell
script in `app/layout.tsx` does the same (Capacitor's bridge can arrive late).

`TOOL_QUERY_PARAMS = ["view", "share-target", "url", "text", "title"]`. Any
other query (`?utm_source=…`) stays on the landing.

### Capacitor: extensionless paths

The static export (`CAPACITOR_BUILD=true`, `output: "export"`, no
`trailingSlash`) writes `/app` as `out/app.html`. Capacitor's Android local
server serves `index.html` for a path it cannot find, so a request for `/app`
would get the landing page back. The same script handles that: if the landing
page is running at a path other than `/` or `/index.html`, and that path is one
of `/app`, `/privacy`, `/terms`, `/offline`, **and** Capacitor reports native
**and** the origin is `localhost` with no port (the asset server; live reload
on `http://localhost:3005` and `next start` never take this branch), it replaces the location with
`<path>.html` plus the query and hash. `isAppPath()` accepts `/app.html`, and
`goToMainTab` keeps whichever spelling the page is on, so tab switches stay on
`/app.html` there. This also covers `/privacy` and `/terms` in Capacitor, which
had the same problem before.

**Unknown paths in the installed app (refinement 8, NF-01).** The asset server
answers *every* extensionless path it has no file for with `index.html`, so
`/nope`, `/nope/deeper` or `/app/zzz` used to show the landing page, dock and
all, at the bad address (android-66, API 35; `out/404.html` never loaded). The
same branch now sends any such path to `/404.html` (the export's not-found
page, from `app/not-found.tsx`; constant `NOT_FOUND_DOCUMENT`). The test is the
asset server's own rule: it substitutes `index.html` only when the last path
segment has no `.`, so on the asset-server origin with native reported:

| Path (trailing `/` ignored) | Result |
|---|---|
| `/`, `/index.html` | rule 2 below (to `/app`) |
| `/app`, `/privacy`, `/terms`, `/offline` | `<path>.html` + query + hash |
| any other path whose last segment has no `.` | `/404.html` (query and hash dropped) |
| last segment has a `.` (`/app.html`, `/404.html`, …) | nothing: the real file is running |

The last row is also what keeps `/404.html` from looping. A dotted path with no
file (`/nope.txt`) gets an empty 404 from Capacitor and no document runs, so it
cannot be caught here. Web is unchanged (no native report, or a port): a browser
tab, `next start`, a static host and live reload all keep their own 404
handling. On the 404 page itself "Go to the home page" is hidden in the
installed shell (`.not-found-action--web`): the home page is the landing, and a
client-side navigation to `/` would render it without this script.

**Not verified on a device.** Agents do not run the native build. See Known issues.

## Content and honesty

The copy claims only what the app does today:

- The free-run line under the hero actions (`LandingAllowance`). The
  prerendered HTML says "Free runs to start. No account needed.", true on any
  deployment; once the server has answered, it states the server's own
  numbers (free runs per device per day, video length). The only number not
  read from the server is the account allowance (10 a day since 2026-11-14,
  `ACCOUNT_FREE_RUNS_PER_DAY`), as everywhere else signed-out copy quotes it.
- What you get: the four result tabs, in the intake's own words (`.wyg-row`,
  `.chip`), so the two pages say it the same way.
- The details at the foot of "What you get" explain: files are deleted from the servers when a
  run finishes; History stays in this browser; when the free runs are used up,
  add your own Gemini key. All three are true (see `CLAUDE.md` "How a run
  flows", `run-history.md`, `byok-api-key.md`).
- No testimonials, user counts, logos or ratings. None exist.

## Where it differs from the boards

- **The foot of "What you get"** adds the History and own-key sentences. The
  board says only that files are deleted. The brief asked for those three
  points to be made, and this is the quietest place for them.
- **The sample card's tabs work.** On the board they are a picture. Here they
  are real ARIA tabs (roving tabindex, arrow keys, Home and End), because a tab
  row that does nothing when clicked reads as broken.
- **The nav on the landing** is the shared `AppNav` with no tab marked current.
  The brand carries `aria-current="page"` on `/`.
- **The dark closing band** is near-black in light mode as drawn. Dark mode has
  no board, so it uses the raised tint `#212522`. It is a card on the page, like
  the step cards, not a contrast band (1.23:1 against the dark paper).

## Chrome

The landing renders the shared chrome like every other route
(`project_shared_app_chrome`): `AppNav` at the top, `SiteFooter`, and
`BottomTabBar activeTab={null}` (hidden in a browser tab by CSS; the installed
shell never sees `/`). Top-bar links go to `/app`, `/app?view=history`,
`/app?view=api-key`, `/app?view=releases`. They are plain links on `/`, because
the tabs are not mounted there.

## Hero fills the first screen (desktop)

At `min-width: 60rem` and `min-height: 40rem` the landing section (the scroller
between the fixed nav and footer) becomes a `container-type: size` container.
`.landing` drops its top padding there, and `.landing-hero` gets
`min-height: 100cqb`, i.e. exactly the visible band, so "How it works" starts
below the fold instead of peeking in, cut off, above the footer. The intro and
card are centred vertically in it (`align-items: center`). No nav or footer
height is subtracted from `100dvh`. Shorter windows and phones keep the natural
height, so the CTAs are never pushed off-screen. Measured in dev (iframe
probes): 1366×768, 1440×900, 1920×1080 and 1024×700, hero = band and `#how`
below the band; 1280×600 and 390×844 unchanged.

`#how` now uses its natural content height, with a modest top inset and
scroll margin. The hero still fills the first desktop screen, but the process
steps no longer reserve another entire screen before the benefits.

## Landing clarity refinement (2026-11-14)

Codex's pass (ab351ad) made `#how` content-sized, put a reassurance line under
the hero actions and turned the "What you get" footnote into a three-part
definition list. The frontend agent's refinement on top kept those structural
changes and brought the new pieces into the editorial system:

- **Allowance line** (`components/LandingAllowance.tsx`, client). Replaces
  Codex's 600-weight ink "Free runs to start. No account needed." and the
  muted "Check your available runs and video-length limits in Analyze before
  you begin." (read as a disclaimer in Android QA). Two lines in the Analyze
  free-runs strip's own vocabulary: an ink-2 0.9375rem sentence with the count
  in a 600-weight ink `strong`, then a muted 0.875rem line.

  | State | Line one | Line two |
  |---|---|---|
  | Prerender, before the reads, server unreachable, limit off | Free runs to start. No account needed. | (blank, height reserved) |
  | Signed out, device allowance known | **3 free runs a day**, no account needed. | Videos up to 3 minutes. [Sign in] for 10 a day. |
  | Signed in, account allowance | **10 free runs a day** with your account. | Videos up to N minutes. |
  | Paid plan | **100 runs a month** on your plan. | Videos up to N minutes. |
  | Key saved on this device | Runs use the Gemini key saved on this device. | Videos up to N minutes. |

  "3 a day" and "10 a day" side by side make the two tiers read as two
  tiers (both daily since 2026-11-14, so signing in reads as more; the period
  word comes from the server's `period`, by plan when absent) (Android QA: newcomers saw 3 on Analyze and 10 on Account and could
  not tell which was true). Numbers come from the same reads `/app` makes:
  `useFreeRuns` (`GET /api/free-runs`), `useMediaLimits` (`GET /api/limits`,
  new `known` flag so a failed read never quotes the fallback minutes) and the
  auth gate (`useAccountEntry`); the "Sign in" clause shows only where sign-in
  is available and nobody is signed in. Line two has `min-height: 1lh` (2lh
  below 30rem, where it wraps), so filling it in moves nothing: measured
  allowance height identical before and after at 320, 390, 412 and 1536.
  Visiting the landing now issues the free-run device token (the same read
  `/app` makes on load).
- **Phone account entry.** Below 48rem the bar pill is hidden and the entry
  was only the last menu row. The inline ink "Sign in" link in line two is the
  phone's visible entry: a text link under the CTAs, not a third button, so the
  green "Start analyzing" stays the one call to action. Chosen over making
  "See how it works" an account button (it would lose the page's own
  explainer jump) and over a separate link line (repeats the tier sentence).
- **Nav label** "Get 10 free runs" (signed out), "Sign up free" from 48rem to
  50rem; see `auth-sign-in.md`, "Landing label, final".
- **Details list** (`.landing-details`). Terms are serif 400 at 1.1875rem,
  like every other heading on the page, instead of Codex's 600 sans; bodies
  keep the foot's ink-2 0.9375rem; the hairline above is the existing
  `.landing-wyg-foot` rule. Phones stack, three columns from 48rem.
- `#how` keeps Codex's natural height (top inset `--space-lg`, scroll margin
  `--space-md`): "See how it works" lands the heading 24px under the bar and
  "What you get" starts 48px below the steps.
- The sample remains an illustrative, labelled example. No verified source
  video/result pair is in the repository; a real one needs owner-supplied media.

## Measured (2026-11-01, `next build` + `next start -p 3015`, Playwright, `/api/*` mocked)

- `/` at 1366×900 and 390×844, light and dark: no horizontal scroll; CTAs
  `/app`, `#how`, `/app`; "See how it works" scrolls `#how` into view; the
  sample tabs change on click and arrow keys.
- `/app`: the free-runs banner is there ("3 free runs left…", Add key →
  `/app?view=api-key`); tab switches push `/app?view=history`.
- `/?view=history` → `/app?view=history` (History); `/?view=api-key` →
  `/app?view=api-key`; `/?share-target=1&text=look https://youtu.be/abc` →
  `/app` with the field filled and the query stripped.
- Installed shell (`videolens_shell=app` override, and a fake Capacitor bridge
  with `isNativePlatform() → true`): `/` → `/app`. Chrome headless shell does
  not honour CDP `display-mode: standalone` emulation, so the real standalone
  media query was not exercised.
- Offline: see `legal-offline-routes.md`.

## Known issues

- **The Capacitor `/app` → `/app.html` hop is untested on a device.** It
  depends on the local server answering an unknown path with `index.html`. If
  it answers 404 instead, `/app` breaks in the APK. Check on a device:
  cold start, a tab switch, Privacy from the More sheet, the hardware back
  button, and a share.
- **The service worker inside Capacitor** precaches `/app`. If Capacitor
  answers `/app` with `index.html`, the cached copy of `/app` is the landing,
  whose script then hops to `/app.html`. That works, but it is a wasted hop.
  It belongs to the same pre-existing, unverified question as `/privacy`.
- ~~A blocked `localStorage` crashes the tool.~~ Fixed in refinement 1 (#5):
  `UploadForm`, `clientId` and `apiKeyStore.set` now catch storage errors.
  Verified with both storages throwing (browser and emulated native): the tool
  loads, Welcome opens once and dismisses, the terms box works, no page errors.
- **Unknown paths are only caught when they are extensionless** (refinement 8).
  `/whatever.xyz` with no file is an empty 404 from Capacitor's asset server,
  before any document runs.
- **The template-literal escape trap.** The redirect script is a template
  literal, so its regex backslashes are doubled (`/\/+$/` in source). A single
  `\/` once collapsed to `//` mid-refinement-1, commented out the rest of the
  line and made the whole `<head>` script a syntax error. On the device that
  showed as no `/` → `/app` redirect and a light landing despite a stored dark
  theme. Refinement 1's harness now `node --check`s the built head script of
  every exported page.

## Changelog

- 2026-11-01 · frontend agent (Phase 5c) · created: tool moved to `/app`, landing at `/`, pre-paint redirects, Capacitor `.html` hop, band tokens
- 2026-11-01 · videolens-ff (lead) · desktop hero fills the visible band (size container + `100cqb`) so "How it works" no longer peeks in above the footer
- 2026-11-01 · videolens-ff (lead) · "What you get" footnote (`.landing-wyg-foot`) runs the full card width (dropped `max-width: 44rem`) with `text-wrap: pretty`
- 2026-11-01 · videolens-ff (lead) · `#how` fills the band and centres its content on desktop, so "See how it works" no longer leaves "What you get" cut off above the footer
- 2026-11-01 · frontend agent (refinement 1) · redirect script moved into the root layout head (no React script warning), Capacitor hop limited to the asset-server origin, storage-crash known issue closed, escape-trap note; verified in `next start`, a separate `next dev`, and an emulated asset server over `out/`
- 2026-11-02 · frontend agent (refinement 8) · NF-01: on the asset-server origin, an unknown extensionless path goes to `/404.html` instead of showing the landing; 404's home-page link hidden in the installed shell; verified on an emulated asset server over `out/`, `node --check` on all 7 exported head scripts
- 2026-11-12 · launch-checklist session · `/` gets its own `<title>` (absolute, not templated), description and canonical; site-wide Open Graph/Twitter card and `og.png` rendered from the hero copy (`docs/frontend/seo-and-discovery.md`)
- 2026-11-14 · frontend agent · top bar and dock gain the Account entry ("Sign in" pill signed out, round initial signed in, nothing until known) via `RouteNav`/`RouteTabBar`; hero CTAs unchanged. See auth-sign-in.md
- 2026-11-14 · frontend agent · signed-out nav entry reads "Get started" (bar pill and phone-menu row) via `signedOutLabel`; outlined secondary so the hero's "Start analyzing" stays the page's one green fill; dock keeps "Account". See auth-sign-in.md

### Browser verification follow-up (2026-11-14)
LandingScreen uses literal /app route hrefs: useMainTab is a client module, so interpolating its APP_PATH export in this server component produced a serialized function URL for Set up a key. Browser verification confirmed the corrected link opens /app?view=api-key. Desktop dark hero, process and benefits sections were visually inspected; mobile not checked.
- 2026-11-14 · codex · `#how` content-sized; reassurance and limit lines under the hero actions; "What you get" foot as a three-part `<dl>`; nav back to "Sign in"
- 2026-11-14 · frontend agent · refinement on codex's pass: `LandingAllowance` states the server's free runs and video length (fallback sentence prerendered, line height reserved, no layout shift) with an inline "Sign in for 10 a month" that is also the phone's visible account entry; details terms in serif to match the page; nav "Get 10 free runs" ("Sign up free" at 48–50rem); stray blank lines tidied
- 2026-11-14 · frontend agent · daily account allowance: signed-out line two "Sign in for 10 a day.", signed-in line "10 free runs a day with your account." (period from the server's `period`); fallback and reserved height unchanged; nav label "Get 10 free runs" / short "Sign up free" kept ("Get 10 free runs a day" would not fit the measured 768-799 bar, and the hero line under it carries the period)
