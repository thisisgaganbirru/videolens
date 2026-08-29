# Capability reporting (`GET /api/capabilities`)

Answers "which parts of this deployment actually work right now, and was that actually checked?" — one row per dependency. Aimed at humans debugging a deployment, the frontend (so a user learns a source is unavailable *before* uploading rather than after), and MCP clients deciding whether a run is worth submitting.

**Files**
- `backend/app/domain/entities.py` — `CapabilityState` (`ok` / `degraded` / `unavailable` / `disabled`), `Capability` (`name`, `state`, `detail`, `probed`), `CapabilityReport`.
- `backend/app/domain/ports.py` — `CapabilityProbe` (`name`, `async check()`).
- `backend/app/application/get_capabilities.py` — `GetCapabilitiesUseCase`, runs the probes and aggregates.
- `backend/app/infrastructure/health/probes.py` — the six concrete probes.
- `backend/app/interface/api/routes.py` — the route.
- `backend/app/container.py` — probe list and order.

## Two audiences, one report

`/api/capabilities` is **unauthenticated**, and the capability strip renders `detail` verbatim, so everything in the response is public. `Capability` therefore carries the same split as `UserFacingError`: `detail` is written for whoever is looking at the app, and `log_detail` is `Field(exclude=True)` — it never serializes, and `GetCapabilitiesUseCase` writes it to one log line per report instead.

What that keeps off the wire, and why each one mattered:

| Kept private | Why |
|---|---|
| The live remaining-run count | A cost-exhaustion oracle. The daily cap exists to bound Gemini spend; publishing its current value tells anyone exactly how much to burn and confirms when it is gone. |
| `ffmpeg` / `yt-dlp` build strings | Exact versions to match against known advisories. |
| The Gemini model name, Redis/bucket reachability wording, replica topology | Deployment shape nobody outside needs. |
| `YTDLP_COOKIES_FILE`, `YTDLP_COOKIES_FROM_BROWSER`, `X-Gemini-Api-Key` | Setting names, per `../error-messaging.md`. |

The user-facing half still carries the consequence — "Links behind a login will fail", "Runs are not saved and will be lost if the server restarts" — because that is what changes what someone does next. `backend/tests/application/test_get_capabilities.py::SerializationTests` locks the invariant at the boundary rather than probe by probe.

## The `probed` flag is the point

The failure this design exists to avoid: a health check that reports `ok` for something that has never once worked, because it only ever read configuration. `probed: false` means "this row reflects settings, not a live check" and is never dressed up as verification.

| Capability | Probe | What it actually does |
|---|---|---|
| `media_tools` | `MediaToolsProbe` | Executes `ffmpeg -version` and `ffprobe -version` (5s timeout) and reports the versions. Resolving a path only proves a file exists; running it proves the container can run it. `probed: true` |
| `url_download` | `UrlDownloadProbe` | Reports the yt-dlp build, degrades past 120 days old (date-stamped releases; a stale copy is the most common reason URL runs start failing), and checks the cookie source — a *configured but missing* cookie file degrades, which is otherwise invisible until someone submits a login-walled link. Fetches nothing. `probed: true` |
| `analysis_engine` | `AnalysisEngineProbe` | Reports whether a shared key is configured, and says outright it was **not** verified — the only way to validate a Gemini key is to spend a request with it. Missing key is `degraded`, not `unavailable`, because BYOK callers still work. Never includes the key. `probed: false` |
| `run_store` | `RunStoreProbe` | Pings Redis in distributed mode. In local mode there is nothing to ping (`RunStore.ping()` returns `True` unconditionally there), so it reports `ok` with `probed: false` and names the store as non-durable rather than calling a method whose answer proves nothing. |
| `object_storage` | `ObjectStoreProbe` | Unconfigured → `disabled` (topology, not a fault). Configured → `head_bucket` against the real bucket, because having four settings filled in says nothing about whether they are correct. |
| `daily_budget` | `DailyBudgetProbe` | Reads `DailyBudget.remaining()` — deliberately read-only; health reporting must never consume the budget it reports on. Exhausted → `unavailable`, uncapped → `disabled`. |

## Aggregation and shape

Overall `state` is the worst reported state, with `disabled` excluded — an unconfigured optional dependency is a deployment shape, not a fault, so it never drags the report down. The endpoint always returns **200**: a non-`ok` body is the payload, not an error.

A probe that raises becomes an `unavailable` row with a fixed message, and the real exception goes to the logs only — the same masking rule `ProcessRunUseCase` uses, and for the same reason (boto and redis errors carry endpoints and credentials). A broken dependency must not also break the endpoint that exists to describe it.

Results are cached for 10s behind an `asyncio.Lock`. The probes spawn subprocesses and open sockets, so an uncached public endpoint would hand any caller a way to spawn processes at will.

## Relationship to the existing health endpoints

Unchanged and still separate:
- `GET /api/health` — flat `{"status": "ok"}`, the Railway `healthcheckPath`. Must stay trivially cheap.
- `GET /api/readiness` — one yes/no for the platform, 503 when run storage is down.
- `GET /api/capabilities` — the per-dependency detail, for people and clients rather than for a load balancer.

**Known gaps**: ~~the frontend does not consume this yet (no capability strip)~~ — the frontend now does; see `docs/frontend/capability-reporting.md`. The MCP server still does not expose it as a tool (and `mcp/` lives on the unmerged `feature/mcp-server` branch). `analysis_engine` cannot be genuinely probed without spending quota.

**Tests**
- `backend/tests/application/test_get_capabilities.py` — ordering, worst-state aggregation, `disabled` not counting, a raising probe becoming `unavailable` without failing the report or leaking its exception text, and the cache window.
- `backend/tests/infrastructure/health/test_probes.py` — each probe's states, including that local-mode `run_store` never calls `ping()`, that `object_storage` never contacts an unconfigured bucket, and that `analysis_engine` never echoes the key.

## Changelog
- 2026-08-29 · main session · added the capability report, its six probes, `DailyBudget.remaining()`, and `S3ObjectStore.check_bucket()`
- 2026-08-29 · frontend agent · marked the "frontend does not consume this" gap closed and pointed it at docs/frontend/capability-reporting.md; no backend code touched
- 2026-08-29 · main session · split `detail` from `log_detail` so the unauthenticated report stops publishing versions, topology and the live budget count
