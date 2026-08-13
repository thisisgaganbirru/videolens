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
- `errors.ts` — `ApiError`.
- `ports.ts` — the interfaces infrastructure adapters implement and hooks
  depend on: `RunsGateway`, `ApiKeyStore`, `VersionLogGateway`,
  `UpdateChecker` (plus their associated `VersionLogEntry`/`UpdateInfo`
  types).

**`infrastructure/`** — concrete adapters, one per external system.
- `runsGateway.ts` — `FetchRunsGateway`: talks to the backend's
  `/api/runs` endpoints, builds the `X-Client-ID`/`X-Gemini-Api-Key`
  headers. Implements `RunsGateway`.
- `apiKeyStore.ts` — `LocalStorageApiKeyStore`: reads/writes the
  bring-your-own-key value in `localStorage`. Implements `ApiKeyStore`.
- `versionLogGateway.ts` — `GithubVersionLogGateway`: fetches the release
  list for the in-app "Releases" panel. Implements `VersionLogGateway`.
- `updateCheck.ts` — `GithubUpdateChecker`: the native-Android-only update
  check (`@capacitor/app` + GitHub releases + `version.json` manifest).
  Implements `UpdateChecker`.
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
- `useRunHistory.ts` — fetches the caller's run history.
- `useVersionLog.ts` — fetches the release list.
- `useUpdateCheck.ts` — wraps the native update check for `UpdateBanner`.

**`app/` + `components/`** — the framework-bound presentation layer
(Next.js routing + React). `app/` holds only what Next.js requires to live
there (route files: `page.tsx`, `layout.tsx`, `manifest.ts`, the legal
pages, global CSS) - `app/page.tsx` is 4 lines and does nothing but render
`<HomeScreen />`. Everything about what the page actually looks like and
does lives in `components/`:
- `HomeScreen.tsx` — the real page body: header, tab navigation, and
  composing `useAnalysisRun()` with the presentational pieces below.
- `panels/{ApiKeyPanel,HistoryPanel,VersionLogPanel}.tsx` — one component
  per tab, each just rendering its matching hook's state.
- `format.ts` — the shared `formatDate` used by the two list-style panels.
- `UploadForm.tsx`, `ResultsView.tsx`, `RunStatusView.tsx`,
  `UpdateBanner.tsx`, `ServiceWorkerRegistration.tsx`, `ui/*` — presentational
  components, unchanged in behavior; only their imports moved to
  `@/domain/entities` where they used to pull from the now-deleted `lib/`.

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
- **New tab/panel** → a component in `components/panels/`, wired into
  `HomeScreen.tsx`'s tab list.
- **Swap out an external system** (e.g. the backend URL scheme, or how
  version info is sourced) → write a new adapter in `infrastructure/`
  satisfying the existing port, point `container.ts` at it. Hooks and
  components don't change.
