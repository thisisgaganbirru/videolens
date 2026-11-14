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

- "A few free runs to start, no account needed." Free runs exist (Phase 5b),
  per device per day. No number is promised, because the limit is server
  configuration.
- What you get: the four result tabs, in the intake's own words (`.wyg-row`,
  `.chip`), so the two pages say it the same way.
- The foot of "What you get" says: files are deleted from the servers when a
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

`#how` ("How it works") is the second screen under the same query: it is also
`min-height: 100cqb`, a centred flex column, with `margin-top: 0` and
`scroll-margin-top: 0`. "See how it works" therefore lands it exactly on the
band with the heading and steps centred (equal space above and below: 291px at
1920×955, 198px at 1366×768), and "What you get" starts below the fold instead
of being cut off by the footer.

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
