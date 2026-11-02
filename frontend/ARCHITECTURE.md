# Frontend architecture

The frontend follows the same layering as the backend (see
`backend/ARCHITECTURE.md`), adapted to what a Next.js app actually needs:
domain types, application hooks that hold state/orchestration, infrastructure
adapters that talk to the outside world, and framework-bound presentation
(`app/` + `components/`). It's intentionally lighter than the backend's
ports/DI setup — no per-adapter dependency injection ceremony, since a
~3,000-line client app doesn't carry the same testability payoff a service
does. The one place that *does* mirror the backend's `container.py` directly
is `infrastructure/container.ts`, because hooks genuinely need one shared
instance of each adapter (e.g. one `ApiKeyStore` backing both `useGeminiApiKey`
and `FetchRunsGateway`'s request headers).

## Layers

**`domain/`** — pure types, no `fetch`/`localStorage`/React.
- `entities.ts` — `RunStatus`, `VideoAnalysis`, `TranscriptSegment`,
  `ScreenTextSegment`, `RunCreateResponse`, `RunStatusResponse`,
  `RunSummary`, `RunListResponse`, `MediaSource`.
- `errors.ts` — `ApiError` (optional HTTP `status`, plus the body's `code`/`limit`/`used`), `NetworkError`,
  `StorageUnavailableError`.
- `ports.ts` — the interfaces infrastructure adapters implement and hooks
  depend on: `RunsGateway`, `ApiKeyStore`, `VersionLogGateway`,
  `UpdateChecker`, `SharedUrlSource` (`take`, `subscribe`, `pending`),
  `HistoryStore`, `FreeRunsGateway`, `DeviceTokenStore`, `FirstRunStore`, `ActiveRunStore` (plus their associated
  `VersionLogEntry`/`UpdateInfo` types). `entities.ts` also holds
  `HistoryRecord`/`HistoryPatch`.

**`infrastructure/`** — concrete adapters, one per external system.
- `runsGateway.ts` — `FetchRunsGateway`: talks to the backend's
  `/api/runs` endpoints, builds the `X-Client-ID`/`X-Gemini-Api-Key`
  headers. Implements `RunsGateway`.
- `apiKeyStore.ts` — `LocalStorageApiKeyStore`: reads/writes the
  bring-your-own-key value in `localStorage`. Implements `ApiKeyStore`.
- `versionLogGateway.ts` — `FetchVersionLogGateway`: reads the backend's
  `GET /api/releases` for the in-app "Releases" panel, mapping the endpoint's
  snake_case rows to `VersionLogEntry`. Implements `VersionLogGateway`.
- `updateCheck.ts` — `ApiUpdateChecker`: the native-Android-only update
  check (`@capacitor/app` for the installed build number, `GET /api/releases`
  for the newest one). Implements `UpdateChecker`.
- `sharedUrlSource.ts` — `WebShareUrlSource`: the link handed to the app from
  outside it, from either the Android share intent (`localStorage` +
  the `videolens-share` event) or the manifest's `share_target` query params.
  Consuming — see `docs/frontend/share-intake.md`. Implements
  `SharedUrlSource`.
- `historyStore.ts` — `IndexedDbHistoryStore`: this browser's run History
  (IndexedDB `videolens`/`runs`, capped at 20, oldest dropped; asks
  `navigator.storage.persist()` once; `BroadcastChannel` for other tabs).
  Opens lazily, so constructing it during prerender is safe. Implements
  `HistoryStore`. See `docs/frontend/run-history.md`.
- `activeRunStore.ts` — `SessionStorageActiveRunStore`: the run this tab
  is watching (`sessionStorage` `videolens-active-run`, try/catch on every
  access), so a reload resumes it. Implements `ActiveRunStore`. See
  `docs/frontend/run-analysis-hook.md`.
- `freeRunsGateway.ts` — `FetchFreeRunsGateway`: `GET /api/free-runs`,
  normalises the body and writes back a replaced device token. Implements
  `FreeRunsGateway`. `deviceTokenStore.ts` — `LocalStorageDeviceTokenStore`
  (`videolens-device-token`, try/catch-wrapped); one instance is shared with
  `FetchRunsGateway`, which sends it as `X-Device-Token` on `createRun` only.
  `clientId.ts` — `getClientId()`, shared by both. See
  `docs/frontend/free-runs.md`.
- `firstRunStore.ts` — `BrowserFirstRunStore`: the installed app's
  first-run flags (`videolens-welcome-v1` in localStorage; the Welcome and
  splash session flags in sessionStorage), every access try/catch'd, with an
  in-memory fallback. Implements `FirstRunStore`. See
  `docs/frontend/first-run.md`.
- `container.ts` — builds one instance of each adapter above and exports
  them; every hook imports from here instead of constructing an adapter
  itself.

**`application/`** — one hook per piece of state/orchestration a component
needs. Each hook owns its `useState`/`useEffect` and calls out to
`infrastructure/container.ts`; components never call an adapter directly.
- `useAnalysisRun.ts` — the core state machine: submit a run, poll it,
  open a past run from history, reset. This is what used to be inline in
  `app/page.tsx`.
- `useGeminiApiKey.ts` — the BYOK value/saved-state and save/clear actions.
- `useFreeRuns.ts` — the free-run allowance: a module-level store (shared by
  the banner and `useAnalysisRun`'s 401/402 handling), `useFreeRuns()` for
  the banner and `blocked` state, and `refreshFreeRuns` / `markFreeRunsUsed` /
  `noteRunAccepted`. Reads `apiKeyStore` through `useSyncExternalStore`.
- `useRunHistory.ts` — reads History from `historyStore` (not the server),
  re-reads on change, owns the poster object URLs; `useHistoryBoot()`.
- `historySync.ts` — React-free History writes used by `useAnalysisRun` and
  the boot: file on submit and on each status response, one-time import from
  `GET /api/runs`, re-check of unfinished runs (404 → expired).
- `useVersionLog.ts` — fetches the release list.
- `useUpdateCheck.ts` — wraps the native update check for `UpdateBanner`.
- `useSharedUrl.ts` — the latest URL shared into the app. Lives here rather
  than in `UploadForm` because a share has to be handled whatever is on
  screen, and the intake is mounted only while the run state is idle.
- `useMainTab.ts` — which of the four shell destinations is showing, held
  in the URL as `/app?view=…` (it was `/?view=…` until Phase 5c) rather than in a component's `useState`. Reading
  and writing that URL is orchestration, so it sits here; `domain/` and
  `infrastructure/` know nothing about routing. Exports `MAIN_TABS`,
  `APP_PATH`, `isAppPath` (also accepts `/app.html`, the Capacitor
  spelling), `mainTabHref`, `goToMainTab` (a plain function, so the Suspense
  fallback can switch tabs without calling `useSearchParams`) and
  `useMainTab`.
- `landingRedirect.ts` — `LANDING_REDIRECT_SCRIPT`, the blocking inline
  script on `/` that sends old tab URLs, share links and the installed shell
  to `/app` before paint, and hops Capacitor's extensionless `/app` to
  `/app.html`. A string, not a hook. See `docs/frontend/landing-page.md`.
- `firstRunScripts.ts` — `SPLASH_INIT_SCRIPT`, the pre-paint script that
  stamps `<html data-splash>` on an installed cold start. Not `"use client"`,
  because a server component inlines it.
- `useFirstRun.ts` — the splash hand-off and the one-time Welcome, as one
  module store (`useSyncExternalStore`): `useSplashHandOff()`, `useWelcome()`.
  See `docs/frontend/first-run.md`.

**`app/` + `components/`** — the framework-bound presentation layer
(Next.js routing + React). `app/` holds only what Next.js requires to live
there (route files: `page.tsx`, `layout.tsx`, `manifest.ts`, the legal
pages, global CSS).

Routes (Phase 5c):

| Route | File | What it is |
|---|---|---|
| `/` | `app/page.tsx` | The landing page (`LandingScreen`), with `LANDING_REDIRECT_SCRIPT` |
| `/app` | `app/app/page.tsx` | The tool: `RoutedHomeScreen` in a `<Suspense>`, plus `Splash` and `Welcome` (installed app only) |
| `/privacy`, `/terms` | `app/privacy`, `app/terms` | Legal pages (`LegalShell`) |
| `/offline` | `app/offline/page.tsx` | The service worker's offline fallback |
| (unknown) | `app/not-found.tsx` | 404 with the shared chrome; exported as `out/404.html` |

Everything about what the page actually looks like and
does lives in `components/`:
- `HomeScreen.tsx` — the real page body for one tab, taking that tab as a
  prop and composing `useAnalysisRun()` with the presentational pieces
  below. `RoutedHomeScreen` (same file) is the variant that reads the tab
  from the URL; `app/app/page.tsx` renders it inside the `<Suspense>` boundary
  `useSearchParams` requires on a statically rendered route, with a real
  Analyze shell as the fallback.
- `LandingScreen.tsx` (server) and `SampleResult.tsx` (client, the sample
  card's ARIA tabs) — the landing page at `/`.
- `Splash.tsx`, `Welcome.tsx` — the installed app's cold-start splash and
  one-time Welcome dialog, driven by `useFirstRun`.
- `AppNav.tsx` — the whole nav band (brand, the four tab links, the mobile
  drawer, the theme toggle) as one component. `HomeScreen` and `LegalShell`
  both render it, which only became possible once the tabs had addresses.
- `theme.ts` — the light/dark constants and the `theme-color` sync, shared
  by `ThemeToggle` and `app/layout.tsx`'s pre-paint script.
- `panels/{ApiKeyPanel,HistoryPanel,VersionLogPanel}.tsx` — one component
  per tab, each just rendering its matching hook's state.
- `format.ts` — `formatDay` ("Oct 30, 2026"), used by the Releases list. (History formats its own dates in `history.ts`.)
- `useMediaQuery.ts` — `useSyncExternalStore` over `matchMedia`; only for when React itself must know the width (History hides sort below 48rem and forces Newest).
- `UploadForm.tsx`, `ResultsView.tsx`, `RunStatusView.tsx`,
  `UpdateBanner.tsx`, `ServiceWorkerRegistration.tsx` — presentational
  components, unchanged in behavior; only their imports moved to
  `@/domain/entities` where they used to pull from the now-deleted `lib/`.

`components/ui/` is gone — it held the animated-background system, deleted
with the Terminal redesign (see `docs/frontend/design-direction-terminal.md`).

## What used to be here

`lib/api.ts`, `lib/types.ts`, `lib/versionLog.ts`, and `lib/updateCheck.ts`
are gone - their contents moved into `domain/`/`infrastructure/` above.
`components/AppMenu.tsx` (a slide-over dialog menu) was deleted outright: an
in-progress redesign had already replaced it with the tab-based navigation
now in `HomeScreen.tsx`, duplicating all four of its panels, but nothing
still imported the old component.

## Adding something new

- **New piece of client state / a new API call** → add a hook in
  `application/`, backed by a port in `domain/ports.ts` if it talks to an
  external system, with the concrete adapter in `infrastructure/` and
  registered in `container.ts`.
- **New tab/panel** → a component in `components/panels/`; add the id to
  `MAIN_TABS` in `application/useMainTab.ts`, its label and icon to
  `TAB_META` in `components/AppNav.tsx`, and its `<section className="tab-view">`
  to `HomeScreen.tsx`. The `.tab-view` class is what gives it the same
  label alignment as every other tab.
- **Swap out an external system** (e.g. the backend URL scheme, or how
  version info is sourced) → write a new adapter in `infrastructure/`
  satisfying the existing port, point `container.ts` at it. Hooks and
  components don't change.

## Changelog

- 2026-11-01 · frontend agent (Phase 5a) · added the `HistoryStore` port + `IndexedDbHistoryStore` adapter, `application/historySync.ts`, `StorageUnavailableError`, `ApiError.status`; `useRunHistory` now reads the browser store
- 2026-11-01 · frontend agent (Phase 5b) · added `FreeRunsGateway` + `DeviceTokenStore` ports and their adapters, `clientId.ts`, `ApiKeyStore.subscribe`, `ApiError.code/limit/used`, `application/useFreeRuns.ts`, `components/FreeRunsBanner.tsx`
- 2026-11-01 · frontend agent (Phase 5c/5d) · routes table (`/` landing, `/app` tool); landingRedirect, firstRunScripts, useFirstRun, firstRunStore, FirstRunStore port, SharedUrlSource.pending(); LandingScreen, SampleResult, Splash, Welcome
- 2026-11-02 · frontend agent (refinement 6) · `ActiveRunStore` port + `SessionStorageActiveRunStore` adapter; `app/not-found.tsx` in the routes table
