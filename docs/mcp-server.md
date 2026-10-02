# MCP server (`mcp/`)

A Model Context Protocol server so terminal AI agents (Claude Code, Cursor, Codex, Antigravity, Claude Desktop) can analyze videos and search their library through VideoLens. A thin Node/TypeScript REST client over the existing API on stdio; no backend surface of its own. Filed here rather than under `backend/` or `frontend/` because it is a third client of the same API.

**Files**
- `mcp/src/index.ts` — the `McpServer` and six tools: `analyze_video` (URL or local `.mp3/.mp4/.mov`; polls with backoff until the run settles or `wait_seconds` runs out, then hands back the `run_id`), `get_run`, `list_recent_runs`, `search_library`, `export_run` (`markdown|json|transcript|srt|vtt|screen_text`), `account_status`. Failures return `isError: true` with the backend's own sentence.
- `mcp/src/client.ts` — `VideoLensClient`; `ApiError` (status + detail + `code`) vs `NetworkError`, the same split as `frontend/infrastructure/apiClient.ts`. File uploads stream via `openAsBlob`.
- `mcp/src/export.ts` — export renderers and their timestamp helpers; the only unit-tested module (`mcp/src/export.test.ts`, `node --test`).
- `mcp/src/config.ts` — env reading; refuses to start without a credential, or with a `VIDEOLENS_API_KEY` that does not start with `vl_`.
- `mcp/src/clientId.ts` — `~/.videolens/client_id`, the anonymous path's non-secret scoping id.
- `mcp/README.md` — user-facing setup; `.mcp.json` at the repo root registers the local build for Claude Code with `VIDEOLENS_API_URL` defaulting to `http://localhost:8000`.

**Credentials** (env only, never a tool argument): `VIDEOLENS_API_KEY` (workspace key, metered, library-backed) or `GEMINI_API_KEY` (BYOK, unmetered, anonymous). Both together: the key identifies the workspace, the Gemini key pays for the model. `VIDEOLENS_API_URL` and `VIDEOLENS_WAIT_SECONDS` are optional.

**Verified**: `npm run build` clean; unit tests pass; a stdio smoke test against a local backend listed all six tools and exercised `search_library`, `account_status`, `get_run` (404), `export_run` (404), the argument guards on `analyze_video`, and the 401 path for a bad API key.

**Not done**: npm publish (`@videolens/mcp`), the remote streamable-HTTP `/mcp` endpoint the plan describes, and a real `analyze_video` run end-to-end (needs a live Gemini key).

## Changelog
- 2026-09-17 · main session · created the server (six tools, stdio) and this doc
