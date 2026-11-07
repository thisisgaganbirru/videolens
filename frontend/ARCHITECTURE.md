# Frontend architecture

Same layering as the backend, lighter: domain types, application hooks that
hold state and orchestration, infrastructure adapters that touch the outside
world, and framework-bound presentation in `app/` + `components/`. The one
piece of DI is `infrastructure/container.ts`, which builds one instance of
each adapter; hooks import from it and components never call an adapter.

Next 16 App Router, React 19, Tailwind 3, Capacitor 8. Every route is
prerendered and the Capacitor build is a static export (`output: "export"`),
which decides most of what follows.

## Codemap (`frontend/`)

**`domain/`** — pure types. `entities.ts` (run, analysis, history, capability
and free-run shapes), `errors.ts` (`ApiError` with `status`/`code`,
`NetworkError`, `StorageUnavailableError`), `platforms.ts` (platform names
and host → platform), `ports.ts` (the interfaces below).

**`infrastructure/`** — one adapter per external system.

| Port | Adapter | Talks to |
|---|---|---|
| `RunsGateway` | `runsGateway.ts` | `/api/runs`; builds `X-Client-ID`, `X-Gemini-Api-Key`, `X-Device-Token` |
| `CapabilitiesGateway` | `capabilitiesGateway.ts` | `/api/capabilities`, no caller identity |
| `FreeRunsGateway`, `DeviceTokenStore` | `freeRunsGateway.ts`, `deviceTokenStore.ts` | `/api/free-runs`; `localStorage` |
| `ApiKeyStore` | `apiKeyStore.ts` | `localStorage` (BYOK) |
| `HistoryStore` | `historyStore.ts` | IndexedDB, capped at 20, `BroadcastChannel` across tabs |
| `ActiveRunStore` | `activeRunStore.ts` | `sessionStorage`, so a reload resumes the run |
| `VersionLogGateway`, `UpdateChecker`, `UpdateDismissalStore` | `versionLogGateway.ts`, `updateCheck.ts`, `updateDismissalStore.ts` | `/api/releases`; `@capacitor/app` for the installed build |
| `SharedUrlSource` | `sharedUrlSource.ts` | Android share intent, web `share_target` |
| `FirstRunStore` | `firstRunStore.ts` | splash and Welcome flags |
| `NativeShell`, `SystemBarsStyler`, `NativeThemeMirror`, `DocumentExporter` | `nativeShell.ts`, `systemBars.ts`, `nativeTheme.ts`, `documentExporter.ts` | Capacitor only; no-ops in a browser |

`apiBase.ts` holds the one `NEXT_PUBLIC_API_BASE_URL` fallback; `clientId.ts`
the persisted client id.

**`application/`** — one hook or React-free module per concern.
`useAnalysisRun` (submit, poll, open from history, reset; the 401 retry and
402 block), `historySync` (every History write), `useRunHistory`,
`useFreeRuns`, `useCapabilities`, `serverReachability` + `gatewayError`
(classifying failed reads), `useGeminiApiKey`, `useVersionLog`,
`useUpdateCheck`, `useSharedUrl`, `useMainTab` (the tab as a URL property,
`/app?view=…`, switched with `pushState` so the shell is never unmounted),
`backNavigation` + `useHardwareBack`, `useResultExport`, `useSoftKeyboard`,
`useSystemBarsTheme`, `useFirstRun`. `landingRedirect.ts`, `firstRunScripts.ts`
and `nativeFontScale.ts` export pre-paint inline scripts (strings), inlined by
`app/layout.tsx`.

**`app/`** — only what Next requires: routes, `layout.tsx` (fonts, the
pre-paint theme / shell / redirect / splash scripts), `manifest.ts`, CSS
(`tokens.css` design tokens, `globals.css` shared classes, two one-off sheets).

| Route | What it is |
|---|---|
| `/` | Landing page; the installed app and legacy `/?view=…` links are redirected to `/app` before paint |
| `/app` | The tool, `RoutedHomeScreen` in a `<Suspense>` whose fallback is a real Analyze shell; plus `Splash` and `Welcome` when installed |
| `/privacy`, `/terms` | `LegalShell` |
| `/offline` | Service-worker fallback; plain `<a>` links on purpose |
| not found | 404 with the shared chrome; the Capacitor head script sends unknown paths here |

**`components/`** — the presentation. `HomeScreen.tsx` is the page body for
one tab (and the sole caller of `useCapabilities`). The chrome is two shells
picked before first paint by `<html data-shell>` (`shell.ts`): `web` is
`AppNav` with four tabs plus `SiteFooter`; `app` (installed, phone width) is
`AppNav` brand-only, `BottomTabBar` (Analyze, History, More) and `MoreSheet`
(API key, Releases, Privacy, Terms, theme). Both are always rendered; CSS
hides one. `panels/` holds one component per tab; `UploadForm`,
`RunStatusView`, `ResultsView`, the notices and `UpdatePrompt` are
presentational; `history.ts`, `releases.ts`, `takeaway.ts`, `format.ts`,
`mediaTerms.ts`, `theme.ts`, `navClick.ts` are pure helpers. `*.preview.tsx`
are dev-only harnesses, never routed.

**`scripts/`** — `build-sw.mjs` generates `public/sw.js` (gitignored) from
`sw/sw.template.js` with the build's hashed assets; `fix-export-segments.mjs`
repairs the static export's RSC segment paths on Windows.

**`android/`** — the Capacitor project plus three Java files the app owns:
`MainActivity`, `NativeThemePlugin` (theme choice as AppCompat night mode,
reports OS night state), `FontScalePlugin`/`FontScaleScript` (system font
scale into the WebView before first paint).

## Invariants

- Nothing reads `localStorage` or `window` during render; a static export
  would mismatch on hydration. Pre-paint scripts stamp `<html>` attributes,
  and hooks read storage in effects (which is why `npm run lint` reports the
  four `set-state-in-effect` findings that are deliberately left).
- Tabs are a query param, never route folders: one page, one shell copy,
  survives the static export, and back walks the tabs on Android.
- Shell mode and theme are never React state.
- Every in-app destination is a real `<a href>`; only a plain left-click is
  intercepted for in-place navigation (`navClick.ts`).
- History is the browser's. The server is asked for `GET /api/runs` once, to
  import runs made before History moved client-side.
- Missing health information never blocks the app: `useCapabilities` and
  `useFreeRuns` go quiet on failure; `serverReachability` turns that into one
  notice.
- Capacitor adapters are no-ops off-device, so the same bundle runs in a tab.

## Cross-cutting

- **Errors**: `gatewayError.ts` maps `NetworkError`/`ApiError` to
  `{ kind, message }`; wording in `docs/error-messaging.md`.
- **Design system**: `docs/frontend/design-direction-editorial.md`; tokens in
  `app/tokens.css`.
- **Offline**: the generated service worker precaches the shell documents and
  hashed assets, never API responses or media; `docs/frontend/legal-offline-routes.md`.
- **Checks**: `npx tsc --noEmit`, `npm run build`, `npm run build:mobile`.
  No test suite yet.

## Adding something new

- Client state or an API call → hook in `application/`, port in
  `domain/ports.ts` if it talks outside, adapter in `infrastructure/`,
  registered in `container.ts`.
- Tab → `MAIN_TABS` (`useMainTab.ts`), `TAB_LABEL` (`AppNav.tsx`), a
  `MoreSheet` row if the installed shell should reach it, a `.tab-view`
  section in `HomeScreen.tsx`, a component in `panels/`.
- Native capability → a port, a Capacitor adapter that is a no-op off-device,
  and the Java side under `android/app/src/main/java/ai/videolens/app/`.

## Changelog

- 2026-11-01 · frontend agent (Phase 5a) · `HistoryStore` + `IndexedDbHistoryStore`, `historySync.ts`, `StorageUnavailableError`, `ApiError.status`; `useRunHistory` reads the browser store
- 2026-11-01 · frontend agent (Phase 5b) · `FreeRunsGateway` + `DeviceTokenStore`, `clientId.ts`, `ApiKeyStore.subscribe`, `ApiError.code/limit/used`, `useFreeRuns.ts`, `FreeRunsBanner.tsx`
- 2026-11-01 · frontend agent (Phase 5c/5d) · routes table (`/` landing, `/app` tool); landingRedirect, firstRunScripts, useFirstRun, firstRunStore, `SharedUrlSource.pending()`; LandingScreen, SampleResult, Splash, Welcome
- 2026-11-02 · frontend agent (refinement 6) · `ActiveRunStore` + `SessionStorageActiveRunStore`; `app/not-found.tsx` in the routes table
- 2026-11-02 · frontend agent (refinement 8) · installed app reaches the 404 via the head script
- 2026-11-02 · frontend agent (refinement 9) · `UpdateDismissalStore`; `NativeShell.onResume`; `UpdateInfo.versionCode`; `domain/platforms.ts`; `components/mediaTerms.ts`
- 2026-11-07 · main session · rewritten as a codemap: port/adapter and route tables, the two shells, invariants, cross-cutting; removed the stale `useMediaQuery.ts` reference
