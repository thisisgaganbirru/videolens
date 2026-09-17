# Library search

`GET /api/library`: search across everything the caller has analyzed. One endpoint, one shape, two depths: a workspace with durable storage gets full-text search over every run it has ever completed; everyone else gets a substring match over their recent live history. The frontend's Library tab and the MCP server's `search_library` both call it.

**Files**
- `backend/app/application/search_library.py` — `SearchLibraryUseCase`. With `archive.enabled` and a `workspace_id` on the principal, delegates to `RunArchive.search`; otherwise filters `RunRepository.list_for_owner(limit=50)` in memory over title, summary, screen text, transcript and source title. `limit` clamped to 1..50, `offset` ≥ 0.
- `backend/app/infrastructure/persistence/run_archive.py` — `PostgresRunArchive`, implements `RunArchive`: `archive(run)` (upsert `runs` + `run_results`), `get`, `list_for_owner`, `search` (Postgres: `to_tsvector('english', …)` over title/summary/transcript/screen_text with `plainto_tsquery`; SQLite: `LIKE` fallback so tests and single-machine deployments work), `ping`, `close`.
- `backend/app/infrastructure/persistence/tiered_run_repository.py` — `TieredRunRepository`: the live store (Redis or dict) first, the archive second. Finished runs whose owner is a workspace are copied to the archive from `set_result`/`set_error`; `get` falls through to the archive after Redis has expired the run; `list_for_owner` merges both, newest first, deduplicated. Anonymous (`client:`) runs never reach the archive, which is what keeps free use client-side-only per the product direction.
- `backend/app/interface/api/routes.py` — `library` route; query params `query` (≤200), `platform`, `since`, `until` (ISO 8601), `limit` (1..50, default 20), `offset`. Response `LibraryResponse{runs: LibraryEntry[], query, limit, offset}`; each entry carries `run_id, status, title, summary, platform, source_url, duration_seconds, completeness, created_at`.

**Ownership**: rows are keyed by `owner_id` (`workspace:{id}`), so every member of a workspace searches the same library and nobody else's.

**Tests**: `tests/application/test_search_library.py` (both depths, filters, paging), `tests/infrastructure/persistence/test_sql_adapters.py` (archive round-trip and search through SQLite), `tests/interface/api/test_account_routes.py` (anonymous shape, `limit` validation).

## Changelog
- 2026-09-17 · main session · created with the archive, tiered repository and search use case
