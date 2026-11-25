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
| `RunsGateway` | `runsGateway.ts` | `/api/runs`; adds `X-Gemini-Api-Key` on create, the rest from `ApiClient` |
| `AuthSession` | `authSession.ts` | Supabase Auth (dynamic import), or `NullAuthSession` when unconfigured |
| `AuthRedirectBrowser` | `authBrowser.ts` | Where Google's consent page opens and how its answer returns: this tab on the web; `@capacitor/browser` and the `ai.videolens.app://auth/callback` deep link (`@capacitor/app`) in the installed app, both lazily imported. Passed to `buildAuthSession` in `container.ts` |
| `AccountGateway` | `accountGateway.ts` | `/api/me`, `/api/me/restore`, `/api/keys` |
| `SavedHistoryGateway` | `savedHistoryGateway.ts` | `/api/history`, `/api/history/{run_id}` (paid saved runs) |
| `AccountHoldSource` | `apiClient.ts` | the shared client itself: tells listeners about every 410 `account_pending_deletion` |
| `ServerAuthStatus`, `CallerIdentity` | `serverAuthStatus.ts`, `apiClient.ts` | the server's `auth` capability (fed by the capabilities adapter, gates the bearer); the identity requests go out as (History `owner`) |
| `CapabilitiesGateway` | `capabilitiesGateway.ts` | `/api/capabilities`, no caller identity; one read in flight, `subscribe` hears every report (the server-auth status re-reads through it while sign-in is unconfirmed) |
| `LimitsGateway` | `limitsGateway.ts` | `/api/limits` (upload length and size per tier), no caller identity |
| `FreeRunsGateway`, `DeviceTokenStore` | `freeRunsGateway.ts`, `deviceTokenStore.ts` | `/api/free-runs`; `localStorage` |
| `BillingGateway` | `billingGateway.ts` | `/api/billing`, `/api/billing/checkout`, `/api/billing/portal` |
| `ApiKeyStore` | `apiKeyStore.ts` | `localStorage` (BYOK) |
| `HistoryStore` | `historyStore.ts` | IndexedDB, capped at 20 per viewer (`isVisibleOwner`), `BroadcastChannel` across tabs; `upsert` creates, `update(patch, when?)` only merges into a row still there that passes `when`; `remove`/`removeOwnedBy` resolve when storage is unavailable |
| `ActiveRunStore` | `activeRunStore.ts` | `sessionStorage`, so a reload resumes the run |
| `VersionLogGateway`, `UpdateChecker`, `UpdateDismissalStore` | `versionLogGateway.ts`, `updateCheck.ts`, `updateDismissalStore.ts` | `/api/releases`; `@capacitor/app` for the installed build |
| `SharedUrlSource` | `sharedUrlSource.ts` | Android share intent, web `share_target` |
| `FirstRunStore` | `firstRunStore.ts` | splash and Welcome flags |
| `NativeShell`, `SystemBarsStyler`, `NativeThemeMirror`, `DocumentExporter` | `nativeShell.ts`, `systemBars.ts`, `nativeTheme.ts`, `documentExporter.ts` | Capacitor only; no-ops in a browser |

`apiBase.ts` holds the one `NEXT_PUBLIC_API_BASE_URL` fallback; `siteOrigin.ts`
the site's own public origin (`NEXT_PUBLIC_SITE_URL`, canonical links, sitemap,
the preview image) and the `NEXT_PUBLIC_NOINDEX` switch; `clientId.ts`
the persisted client id. `apiClient.ts` is the shared caller transport every
caller-scoped gateway (runs, free runs, account) uses: `X-Client-ID` always,
`X-Device-Token` when held, `Authorization: Bearer` when signed in;
`sendAs` also returns the identity a request went out as, which History files
a run under. `authSessionStamp.ts` names the provider's storage key and
exports the pre-paint script that stamps `data-session` on `<html>`;
`layoutHints.ts` keeps the small localStorage hints (runs spent, plan) and
their pre-paint script, so reserved space matches before hydration.

**`application/`** — one hook or React-free module per concern.
`useAnalysisRun` (submit, poll, open from history, reset; the 401 retry and
402 block), `historySync` (every History write), `useRunHistory`,
`useFreeRuns`, `useBilling`, `useCapabilities`, `serverReachability` + `gatewayError`
(classifying failed reads), `useGeminiApiKey`, `useVersionLog`,
`useUpdateCheck`, `useSharedUrl`, `useMainTab` (the tab as a URL property,
`/app?view=…`, switched with `pushState` so the shell is never unmounted),
`backNavigation` + `useHardwareBack`, `useResultExport`, `useSoftKeyboard`,
`useSystemBarsTheme`, `useFirstRun`, `useAuthSession` (`useAuthUser`,
`useEmailCodeSignIn`, `signOut`, which also removes account-owned History
rows), `useAccount`, `useApiKeys`, `useAccountEntry` (the Account entry for routes other than `/app`, used by `RouteNav`/`RouteTabBar`),
`useMediaLimits` (reads `limitsGateway`), `useLayoutHints` (writes
`layoutHints`), `useDocumentTitle` (the view's tab title, re-asserted when
Next overwrites it), `accountAllowance` (the owner's quoted allowances, a
plain module so server components can import the numbers),
`useSavedHistory` (paid saved runs) and `accountHold` (the deletion hold). `landingRedirect.ts`, `firstRunScripts.ts`
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
`AppNav` brand-only, `BottomTabBar` (Analyze, History, Account when sign-in is available, More) and `MoreSheet`
(API key, Releases, Privacy, Terms, theme). Both are always rendered; CSS
hides one. `panels/` holds one component per tab; `UploadForm`,
`RunStatusView`, `ResultsView`, the notices and `UpdatePrompt` are
presentational; `history.ts`, `releases.ts`, `takeaway.ts`, `format.ts`,
`mediaTerms.ts`, `theme.ts`, `navClick.ts` are pure helpers. `*.preview.tsx`
are dev-only harnesses, never routed.

**`scripts/`** — `build-sw.mjs` generates `public/sw.js` (gitignored) from
`sw/sw.template.js` with the build's hashed assets; `fix-export-segments.mjs`
repairs the static export's RSC segment paths on Windows; `inject-csp.mjs`
writes the hash-based CSP `<meta>` into every prerendered document, before
`build-sw.mjs` so the cached shell carries it.

**`security/csp.mjs`** — outside the layers, never in the browser bundle:
the one source of the Content-Security-Policy and the other security
headers. `next.config.mjs` sends them on the web build (as a function of
`phase`, so `next dev` gets `'unsafe-eval'`); the static export gets the
same policy from the injected meta. See `docs/frontend/security-headers.md`.

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
- Inline scripts are limited to the pre-paint set whose hashes the CSP
  carries; a new one is blocked until `security/csp.mjs` knows it.

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
  `MoreSheet` row if the installed shell should reach it, a
  `<main className="view-scroll">` branch in `HomeScreen.tsx`, a component in
  `panels/`.
- Native capability → a port, a Capacitor adapter that is a no-op off-device,
  and the Java side under `android/app/src/main/java/ai/videolens/app/`.

## Changelog

- 2026-11-01 · frontend agent (Phase 5a) · `HistoryStore` + `IndexedDbHistoryStore`, `historySync.ts`, `StorageUnavailableError`, `ApiError.status`; `useRunHistory` reads the browser store
- 2026-11-01 · frontend agent (Phase 5b) · `FreeRunsGateway` + `DeviceTokenStore`, `clientId.ts`, `ApiKeyStore.subscribe`, `ApiError.code/limit/used`, `useFreeRuns.ts`, `FreeRunsBanner.tsx`
- 2026-11-01 · frontend agent (Phase 5c/5d) · routes table (`/` landing, `/app` tool); landingRedirect, firstRunScripts, useFirstRun, firstRunStore, `SharedUrlSource.pending()`; LandingScreen, SampleResult, Splash, Welcome
- 2026-11-02 · frontend agent (refinement 6) · `ActiveRunStore` + `SessionStorageActiveRunStore`; `app/not-found.tsx` in the routes table
- 2026-11-02 · frontend agent (refinement 8) · installed app reaches the 404 via the head script
- 2026-11-02 · frontend agent (refinement 9) · `UpdateDismissalStore`; `NativeShell.onResume`; `UpdateInfo.versionCode`; `domain/platforms.ts`; `components/mediaTerms.ts`
- 2026-11-07 · frontend agent · build-time security section: `security/csp.mjs`, `scripts/inject-csp.mjs`
- 2026-11-07 · main session · rewritten as a codemap: port/adapter and route tables, the two shells, invariants, cross-cutting; removed the stale `useMediaQuery.ts` reference
- 2026-11-08 · frontend subagent (auth phase 2) · `AuthSession` + `SupabaseAuthSession`/`NullAuthSession`, `AccountGateway`, shared `ApiClient` (runs and free-runs gateways now take it), hooks `useAuthSession`/`useAccount`/`useApiKeys`, `account` tab and `AccountPanel`; see docs/frontend/auth-sign-in.md
- 2026-11-08 · frontend subagent (auth phase 2, review fixes) · `ServerAuthStatus` + `MemoryServerAuthStatus`, `CallerIdentity` on `ApiClient`, `HistoryRecord.owner` and `recordGone`; see docs/frontend/auth-sign-in.md
- 2026-11-13 · frontend agent · `BillingGateway` + `FetchBillingGateway`, hook `useBilling` (`useBilling`, `useBillingActions`), `takeSearchParam` in `useMainTab`; see docs/frontend/billing.md
- 2026-11-14 · frontend agent · `SavedHistoryGateway` + `FetchSavedHistoryGateway`, `AccountHoldSource` (the `ApiClient` itself), `AccountGateway.restoreAccount`, hooks `useSavedHistory` and `accountHold` (`useAccountHold`, `useAccountRestore`, `useRestoredEpoch`), `ConfirmDialog`; see docs/frontend/saved-history.md
- 2026-11-20 · Claude (frontend agent) · `HistoryStore.remove`/`removeOwnedBy`, `AuthSession.recover`, `ApiClient.sendAs` + `AsOwner` results from `RunsGateway`, `ApiError.retryAfter`, `createRun(source, signal)`; codemap now lists `limitsGateway`/`useMediaLimits`, `layoutHints`/`useLayoutHints`, `authSessionStamp`, `useDocumentTitle`, `accountAllowance`, `useSavedHistory`/`accountHold`; "Adding something new" names `view-scroll`, not `.tab-view`
- 2026-11-20 · Claude (frontend agent) · `HistoryStore.update` (merge-only, never creates); `FetchFailedError`/`SignInUnconfirmedError` under `NetworkError`; `AuthSession` hears other tabs' sign-out via `storage`
- 2026-11-21 · Claude (frontend agent) · `ServerAuthState` gains `degraded`; `ServerAuthStatus.requestReport`/`setReader` (wired in `container.ts`); `CapabilitiesGateway.subscribe` and a shared in-flight read; `ANONYMOUS_OWNER` now in `domain/entities.ts`
- 2026-11-21 · Claude (frontend agent) · `HistoryStore.update(patch, when)`, per-viewer cap, `isVisibleOwner` in domain; `removeOwnedBy` now only for account deletion
- 2026-11-22 · frontend agent · `AuthRedirectBrowser` port + `SystemAuthBrowser` adapter (`authBrowser.ts`) for Google sign-in, injected into `buildAuthSession`; hooks `useGoogleSignIn`/`useGoogleReturnLanding`; see docs/frontend/auth-sign-in.md
