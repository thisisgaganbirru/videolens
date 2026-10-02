# Library panel

The `library` tab: search everything you have analyzed, filter by platform, page through results, reopen a run. Same component on every deployment; the depth of the search is the backend's decision (see `docs/backend/library-search.md`).

**Files**
- `frontend/components/panels/LibraryPanel.tsx` — search input (`type="search"`), platform chips (`.chip`, `aria-pressed`; YouTube, Instagram, TikTok, Facebook, Twitter, Upload), result rows reusing `.history-row` plus `.library-row` with a clamped summary, newer/older paging. `onOpenRun(run_id)` hands off to `HomeScreen`'s existing open-from-history path.
- `frontend/application/useLibrary.ts` — debounced query (250 ms), `PAGE_SIZE = 20`, `hasMore` when a full page came back. `loading` is derived (`answered !== request`) rather than set in an effect, which is what keeps `react-hooks/set-state-in-effect` quiet.
- `frontend/infrastructure/libraryGateway.ts` — `FetchLibraryGateway.search` over `GET /api/library`.
- `frontend/domain/entities.ts` — `LibraryEntry`, `LibraryQuery`, `LibraryResponse`; `frontend/domain/ports.ts` — `LibraryGateway`.
- `frontend/app/globals.css` — the LIBRARY block (`.library-controls`, `.library-search`, `.library-filters`, `.chip`, `.library-row`, `.library-summary`).
- `frontend/application/useMainTab.ts`, `frontend/components/AppNav.tsx`, `frontend/components/HomeScreen.tsx` — the tab itself (`MAIN_TABS` is now six entries: analyze, history, library, account, api-key, releases).

**Tests**: none (see `account-panel.md`).

## Changelog
- 2026-09-17 · main session · created with the library tab
