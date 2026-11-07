# Frontend architecture

The frontend follows the same layering as the backend (see
`backend/ARCHITECTURE.md`), adapted to what a Next.js app actually needs:
domain types, application hooks that hold state/orchestration, infrastructure
adapters that talk to the outside world, and framework-bound presentation
(`app/` + `components/`). It's intentionally lighter than the backend's
ports/DI setup — no per-adapter dependency injection ceremony, since a
client app doesn't carry the same testability payoff a service does. The one
place that *does* mirror the backend's `container.py` directly is
`infrastructure/container.ts`, because hooks genuinely need one shared
instance of each adapter (e.g. one `ApiKeyStore` backing both
`useGeminiApiKey` and `FetchRunsGateway`'s request headers, and one
`DeviceTokenStore` behind both the free-runs read and run creation).

Next 16 (App Router), React 19, Tailwind 3, Capacitor 8. Every route is
statically rendered; the Capacitor build is `output: "export"`, which is why
tabs are a query param and why nothing may read `localStorage` during render.

## Layers

**`domain/`** — pure types, no `fetch`/`localStorage`/React.
- `entities.ts` — `RunStatus`, `VideoAnalysis`, `TranscriptSegment`,
  `ScreenTextSegment`, `SourceMetadata`, `AnalysisCompleteness`,
  `RunCreateResponse`, `RunStatusResponse`, `RunSummary`, `RunListResponse`,
  `MediaSource`, `HistoryRecord`/`HistoryPatch`, `CapabilityState`/
  `Capability`/`CapabilityReport`, `FreeRunsStatus`.
- `platforms.ts` — platform display names (`platformName`, `knownPlatformName`,
  `platformKey`) and the platform of a link judged from its host
  (`platformFromUrl`, `linkHost`); shared by History and the result screen.
- `errors.ts` — `ApiError` (optional HTTP `status`, plus the body's
  `code`/`limit`/`used`), `NetworkError`, `StorageUnavailableError`.
- `ports.ts` — the interfaces infrastructure adapters implement and hooks
  depend on: `RunsGateway`, `HistoryStore`, `CapabilitiesGateway`,
  `ActiveRunStore`, `ApiKeyStore`, `DeviceTokenStore`, `FreeRunsGateway`,
  `VersionLogGateway`, `UpdateChecker`, `UpdateDismissalStore`,
  `SharedUrlSource` (`take`, `subscribe`, `pending`), `SystemBarsStyler`,
  `NativeThemeMirror`, `FirstRunStore`, `NativeShell`, `DocumentExporter`,
  plus their associated types (`VersionLogEntry`, `UpdateInfo`,
  `PaintedTheme`/`ThemeChoice`, `MarkdownDocument`).

**`infrastructure/`** — concrete adapters, one per external system, every
one registered in `container.ts`.
- `apiBase.ts` — `API_BASE_URL`, the one `NEXT_PUBLIC_API_BASE_URL` fallback
  (`http://localhost:8000`), inlined at build time so an image or APK is
  bound to one backend.
- `runsGateway.ts` — `FetchRunsGateway`: talks to the backend's
  `/api/runs` endpoints, builds the `X-Client-ID`/`X-Gemini-Api-Key`/
  `X-Device-Token` headers. Implements `RunsGateway`.
- `capabilitiesGateway.ts` — `FetchCapabilitiesGateway`: `GET
  /api/capabilities`, normalising rather than trusting the body, with no
  caller identity attached. See `docs/frontend/capability-reporting.md`.
- `freeRunsGateway.ts` — `FetchFreeRunsGateway`: `GET /api/free-runs`,
  writes back a replaced device token. `deviceTokenStore.ts` —
  `LocalStorageDeviceTokenStore` (`videolens-device-token`). `clientId.ts` —
  `getClientId()`, the persisted `X-Client-ID`. See
  `docs/frontend/free-runs.md`.
- `apiKeyStore.ts` — `LocalStorageApiKeyStore`: the bring-your-own-key
  value, with `subscribe` so the free-runs banner can react to a key being
  saved. Implements `ApiKeyStore`.
- `historyStore.ts` — `IndexedDbHistoryStore`: this browser's run History
  (IndexedDB `videolens`/`runs`, capped at 20, oldest dropped; asks
  `navigator.storage.persist()` once; `BroadcastChannel` for other tabs).
  Opens lazily, so constructing it during prerender is safe. See
  `docs/frontend/run-history.md`.
- `activeRunStore.ts` — `SessionStorageActiveRunStore`: the run this tab
  is watching, so a reload resumes it. See
  `docs/frontend/run-analysis-hook.md`.
- `versionLogGateway.ts` — `FetchVersionLogGateway`: reads `GET
  /api/releases` for the Releases tab. `updateCheck.ts` — `ApiUpdateChecker`:
  the native-Android-only update check (`@capacitor/app` for the installed
  build number, the same endpoint for the newest one).
  `updateDismissalStore.ts` — the dismissed `versionCode`. See
  `docs/frontend/android-update-check.md`.
- `sharedUrlSource.ts` — `WebShareUrlSource`: the link handed to the app from
  outside it, from either the Android share intent (`localStorage` +
  the `videolens-share` event) or the manifest's `share_target` query params.
  See `docs/frontend/share-intake.md`.
- `firstRunStore.ts` — `BrowserFirstRunStore`: the installed app's
  first-run flags, every access try/catch'd with an in-memory fallback. See
  `docs/frontend/first-run.md`.
- The Capacitor-only adapters, each a no-op in a browser: `nativeShell.ts`
  (`CapacitorNativeShell`: hardware back, resume, exit), `systemBars.ts`
  (`CapacitorSystemBarsStyler`: status/gesture bar icon colour),
  `nativeTheme.ts` (`CapacitorNativeThemeMirror`: the app module's own
  `NativeTheme` plugin, which applies the theme choice as AppCompat night
  mode and reports the OS night state), `documentExporter.ts`
  (`CapacitorDocumentExporter`: share/save a finished report; on Android it
  writes a real `.md` and opens the share sheet with the file, in a browser
  it is the Web Share API or a blob download).
- `container.ts` — builds one instance of each adapter above and exports
  them; every hook imports from here instead of constructing an adapter
  itself.

**`application/`** — one hook, or one React-free module, per piece of
state/orchestration a component needs. Each hook owns its
`useState`/`useEffect` and calls out to `infrastructure/container.ts`;
components never call an adapter directly.
- `useAnalysisRun.ts` — the core state machine: submit a run, poll it,
  open a past run from history, reset; handles the free-run 401 retry and
  402 block. See `docs/frontend/run-analysis-hook.md`.
- `historySync.ts` — React-free History writes used by `useAnalysisRun` and
  the boot: file on submit and on each status response, one-time import from
  `GET /api/runs`, re-check of unfinished runs (404 → expired).
- `useRunHistory.ts` — reads History from `historyStore` (not the server),
  re-reads on change, owns the poster object URLs; `useHistoryBoot()`.
- `useFreeRuns.ts` — the free-run allowance as a module-level store shared
  by the banner and `useAnalysisRun`; `refreshFreeRuns` / `markFreeRunsUsed` /
  `noteRunAccepted`.
- `useCapabilities.ts` — one fetch of `/api/capabilities` on mount, silent
  on failure; `isNoticeable`.
- `serverReachability.ts` — the one place that knows the last launch read
  could not reach the server; fed by the two reads above, drives
  `ReachabilityNotice`. `gatewayError.ts` — the shared
  `NetworkError`/`ApiError` → `{ kind, message }` classification.
- `useGeminiApiKey.ts` — the BYOK value/saved-state and save/clear actions.
- `useVersionLog.ts` — fetches the release list. `useUpdateCheck.ts` — the
  native update check plus its remembered dismissal, for `UpdatePrompt`.
- `useSharedUrl.ts` — the latest URL shared into the app. Lives here rather
  than in `UploadForm` because a share has to be handled whatever is on
  screen.
- `useMainTab.ts` — which of the four destinations is showing, held in the
  URL as `/app?view=…` rather than in a component's `useState`. Exports
  `MAIN_TABS`, `APP_PATH`, `isAppPath` (also accepts `/app.html`, the
  Capacitor spelling), `mainTabHref`, `goToMainTab` (a `pushState`, so the
  shell is never unmounted and Android back walks the tabs) and `useMainTab`.
- `backNavigation.ts` + `useHardwareBack.ts` — what "back" means in the
  installed app (the previous in-app entry, else Analyze; a top open
  `<dialog>` is cancelled first), and the Android hardware-back binding.
- `useResultExport.ts` — share/save a result through `DocumentExporter`.
  `useSoftKeyboard.ts` — infers the on-screen keyboard and hides the dock.
  `useSystemBarsTheme.ts` — keeps the native bars and night mode in step
  with `<html data-theme>`. `nativeFontScale.ts` — the pre-paint script that
  applies Android's font scale as the root font size.
- `landingRedirect.ts` — `LANDING_REDIRECT_SCRIPT`, the blocking inline
  script on `/` that sends old tab URLs, share links and the installed shell
  to `/app` before paint, and hops Capacitor's extensionless `/app` to
  `/app.html`. A string, not a hook. See `docs/frontend/landing-page.md`.
- `firstRunScripts.ts` — `SPLASH_INIT_SCRIPT`, the pre-paint script that
  stamps `<html data-splash>` on an installed cold start. `useFirstRun.ts` —
  the splash hand-off and the one-time Welcome as one module store. See
  `docs/frontend/first-run.md`.

**`app/` + `components/`** — the framework-bound presentation layer
(Next.js routing + React). `app/` holds only what Next.js requires to live
there: route files, `layout.tsx` (fonts self-hosted by `next/font`, the
pre-paint theme and shell-mode scripts), `manifest.ts`, and the CSS
(`tokens.css` is every design token, light on `:root` and dark under
`[data-theme="dark"]`; `globals.css` the shared class vocabulary;
`landing.css` and `first-run.css` the two one-offs).

Routes:

| Route | File | What it is |
|---|---|---|
| `/` | `app/page.tsx` | The landing page (`LandingScreen`), with `LANDING_REDIRECT_SCRIPT` in the root layout's head |
| `/app` | `app/app/page.tsx` | The tool: `RoutedHomeScreen` in a `<Suspense>` whose fallback is a real Analyze shell, plus `Splash` and `Welcome` (installed app only) |
| `/privacy`, `/terms` | `app/privacy`, `app/terms` | Legal pages (`LegalShell`) |
| `/offline` | `app/offline/page.tsx` | The service worker's offline fallback; plain `<a>` links on purpose |
| (unknown) | `app/not-found.tsx` | 404 with the shared chrome; exported as `out/404.html`, which the Capacitor head script sends unknown paths to |

The manifest keeps `id: "/"` (what every existing install already has) with
`start_url: "/app"`, `scope: "/"`, two shortcuts and a `GET` `share_target`
at `/app?share-target=1`.

Two shells, one markup. `components/shell.ts` defines `ShellMode`: `web` (a
browser tab: `AppNav` top bar with the four tabs, phone hamburger menu,
`SiteFooter`) and `app` (installed PWA or Capacitor, up to 37.5rem:
`AppNav` with brand and theme only, `BottomTabBar` with Analyze, History and
More, and `MoreSheet` holding API key, Releases, Privacy, Terms and the
System/Light/Dark choice). The pre-paint script in `layout.tsx` stamps
`<html data-shell>`; both variants are always rendered and CSS shows one,
never React state, because every route is prerendered.
`localStorage.videolens_shell = "app"` forces the installed chrome in a
normal tab for testing.

Everything about what the page looks like and does lives in `components/`:
- `HomeScreen.tsx` — the real page body for one tab, taking that tab as a
  prop and composing `useAnalysisRun()` with the pieces below; the single
  caller of `useCapabilities()`. `RoutedHomeScreen` (same file) reads the
  tab from the URL.
- `LandingScreen.tsx` (server) and `SampleResult.tsx` (client, the sample
  card's ARIA tabs) — the landing page at `/`.
- `Splash.tsx`, `Welcome.tsx` — the installed app's cold-start splash and
  one-time Welcome dialog, driven by `useFirstRun`.
- `AppNav.tsx` (exports `TAB_LABEL`), `BottomTabBar.tsx`, `MoreSheet.tsx`,
  `AppBackLink.tsx` (the "‹ Back" above API key, Releases, Privacy and
  Terms), `SiteFooter.tsx`, `LegalShell.tsx`, `ThemeToggle.tsx`,
  `navClick.ts` (`isPlainLeftClick`, so every destination stays a real link).
- `theme.ts` — the light/dark constants, the stored preference, and the
  `theme-color` sync, shared by `ThemeToggle`, the More sheet and
  `app/layout.tsx`'s pre-paint script.
- `panels/{ApiKeyPanel,HistoryPanel,VersionLogPanel}.tsx` — one component
  per tab, each just rendering its matching hook's state. `history.ts`,
  `releases.ts`, `takeaway.ts`, `format.ts`, `mediaTerms.ts` — pure helpers
  (filters/sort and relative dates, version parsing, TL;DR splitting,
  `formatDay`, the media-terms flag) with no React or fetch in them.
- `UploadForm.tsx`, `RunStatusView.tsx`, `ResultsView.tsx`,
  `FreeRunsBanner.tsx`, `CapabilityNotice.tsx`, `ReachabilityNotice.tsx`,
  `UpdatePrompt.tsx`, `ServiceWorkerRegistration.tsx` — presentational.
- `*.preview.tsx` — dev-only harnesses that render a component through
  every state. Not routed; mount one temporarily under `app/` to look at
  it, then remove the mount.

Build helpers in `scripts/`: `build-sw.mjs` generates `public/sw.js` (and
`out/sw.js` for the export) from `sw/sw.template.js` with the build's hashed
asset list, after every build; `fix-export-segments.mjs` moves the static
export's per-segment RSC files to the paths the client requests, which Next
16.4 writes wrongly on Windows. `public/sw.js` is gitignored.

The native side (`android/app/src/main/java/ai/videolens/app/`):
`MainActivity` (applies the night background before the first frame and
registers the plugins), `NativeThemePlugin` (the theme preference as
AppCompat night mode, plus the OS night state), `FontScalePlugin` and
`FontScaleScript` (pin WebView text zoom to 100 and hand the system font
scale to `nativeFontScale.ts`). Everything else native is Capacitor's.

## What used to be here

`lib/api.ts`, `lib/types.ts`, `lib/versionLog.ts`, and `lib/updateCheck.ts`
are gone — their contents moved into `domain/`/`infrastructure/` above.
`components/AppMenu.tsx` (a slide-over dialog menu) and `components/ui/`
(the animated-background system) were deleted with the Terminal redesign
(`docs/frontend/design-direction-terminal.md`), which the Editorial direction
(`docs/frontend/design-direction-editorial.md`, 2026-11-01) has since
superseded. `components/useMediaQuery.ts` was described here once but never
committed; History's sort control does not need it.

## Adding something new

- **New piece of client state / a new API call** → add a hook in
  `application/`, backed by a port in `domain/ports.ts` if it talks to an
  external system, with the concrete adapter in `infrastructure/` and
  registered in `container.ts`.
- **New tab/panel** → a component in `components/panels/`; add the id to
  `MAIN_TABS` in `application/useMainTab.ts`, its label to `TAB_LABEL` in
  `components/AppNav.tsx`, a row in `MoreSheet.tsx` if the installed shell
  should reach it, and its `<section className="tab-view">` to
  `HomeScreen.tsx`. The `.tab-view` class is what gives it the same label
  alignment as every other tab.
- **Swap out an external system** (e.g. the backend URL scheme, or how
  version info is sourced) → write a new adapter in `infrastructure/`
  satisfying the existing port, point `container.ts` at it. Hooks and
  components don't change.
- **Anything native** → a port in `domain/ports.ts`, a Capacitor adapter in
  `infrastructure/` that is a no-op when `Capacitor.isNativePlatform()` is
  false, and the Java side under `android/app/src/main/java/ai/videolens/app/`.

## Changelog

- 2026-11-01 · frontend agent (Phase 5a) · added the `HistoryStore` port + `IndexedDbHistoryStore` adapter, `application/historySync.ts`, `StorageUnavailableError`, `ApiError.status`; `useRunHistory` now reads the browser store
- 2026-11-01 · frontend agent (Phase 5b) · added `FreeRunsGateway` + `DeviceTokenStore` ports and their adapters, `clientId.ts`, `ApiKeyStore.subscribe`, `ApiError.code/limit/used`, `application/useFreeRuns.ts`, `components/FreeRunsBanner.tsx`
- 2026-11-01 · frontend agent (Phase 5c/5d) · routes table (`/` landing, `/app` tool); landingRedirect, firstRunScripts, useFirstRun, firstRunStore, FirstRunStore port, SharedUrlSource.pending(); LandingScreen, SampleResult, Splash, Welcome
- 2026-11-02 · frontend agent (refinement 6) · `ActiveRunStore` port + `SessionStorageActiveRunStore` adapter; `app/not-found.tsx` in the routes table
- 2026-11-02 · frontend agent (refinement 8) · routes table: installed app reaches the 404 via the head script
- 2026-11-02 · frontend agent (refinement 9) · `UpdateDismissalStore` port + `LocalStorageUpdateDismissalStore` adapter (container `updateDismissalStore`); `NativeShell.onResume`; `UpdateInfo.versionCode`; pure `domain/platforms.ts` (platform display names, URL-host platform); `components/mediaTerms.ts` (terms flag + accept list shared by UploadForm and HomeScreen)
- 2026-11-07 · main session · refreshed against the tree: the two shells (`BottomTabBar`, `MoreSheet`, `AppBackLink`, `SiteFooter`, `shell.ts`), the capability/reachability modules, `apiBase.ts`, every Capacitor-only port and adapter, `scripts/`, the native plugins; removed the stale `useMediaQuery.ts` reference
