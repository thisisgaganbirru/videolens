# Run history panel

Shows the caller's own past runs (newest first, backend-capped at 20) and lets them reopen one.

**Files**
- `frontend/application/useRunHistory.ts` — fetches on mount via `runsGateway.listRuns()`.
- `frontend/components/panels/HistoryPanel.tsx` — renders loading/error/empty/list states; each item shows title (or "Untitled run"/"Failed run" fallback) and `formatDate(created_at) · status`.
- `frontend/components/format.ts` — the shared `formatDate` helper (also used by the release-notes panel).

**Ownership**: history is scoped server-side by the caller's `Principal` (see `backend/docs/auth.md` — anonymous callers are scoped by `X-Client-ID`), not filtered client-side.

**Known issue**: none — this is a straightforward fetch-and-render panel.

**Tests**: none (see `run-analysis-hook.md` — no frontend unit tests currently).
