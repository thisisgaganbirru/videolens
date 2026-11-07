# Backend architecture

The backend is layered as clean architecture: each layer only depends on the
layers below it, and the direction of dependency always points *inward*,
toward the domain. Nothing in `domain/` or `application/` imports FastAPI,
Redis, boto3, or any other framework/driver — those only appear in
`infrastructure/` and `interface/`.

```
domain          <- application    <- infrastructure
                <- application    <- interface (api, worker)
```

`interface/` and `infrastructure/` both depend on `domain/` and
`application/`, but never on each other directly — they're wired together
only in `container.py`. (Three known exceptions, all cross-cutting config,
logging and one adapter-defined exception, are recorded in
`docs/engineering-standards.md`; nothing enforces the rule mechanically yet.)

## Layers

**`domain/`** — pure business types and rules, no I/O.
- `entities.py` — `Run`, `RunStatus`, `VideoAnalysis` (with
  `TranscriptSegment`/`ScreenTextSegment` lists), `AnalysisCompleteness`
  (`full` / `captions_only`; kept off `VideoAnalysis` on purpose, because that
  model is Gemini's response schema and this is a fact the server knows),
  `SourceMetadata` (what yt-dlp knew about the post), `SavedUpload`,
  `MediaVisuals` (the history poster and display size), `CaptionTrack`,
  `Capability`/`CapabilityState`/`CapabilityReport`, `ReleaseEntry`/
  `LatestRelease`/`ReleaseIndex`, `FreeRunStatus`/`FreeRunClaim`, `Principal`.
- `errors.py` — the exceptions a use case can raise. `UserFacingError` is the
  base for errors whose `str()` is shown on a phone and whose `log_detail`
  goes only to the operator log (`MediaValidationError`,
  `AnalysisUnavailableError`, `GeminiConfigurationError`). The rest are
  `TermsNotAcceptedError`, `InvalidSourceError`, `QuotaExceededError` and
  `RateLimitedError` (both carry `retry_after_seconds`),
  `RunSchedulingError`, `RunNotFoundError`, `DeviceTokenInvalidError`,
  `FreeRunsExhaustedError` (carries `limit`/`used`).
- `policies.py` — pure functions/constants that encode a business rule
  without needing any infrastructure: `quota_key_from_headers`,
  `is_valid_client_id`, `is_run_stale`.
- `run_facts.py` — pure derivations of the media facts the history grid
  shows (`describe_run` → source kind, normalized platform, duration,
  orientation, summary snippet). Routes call it and only map the result.
- `ports.py` — `Protocol` interfaces the application layer depends on:
  `RunRepository`, `MediaProcessor` (validate tools, save/download source,
  `fetch_captions`, normalize, `describe_visuals`), `SourceResolver` (one
  route to a URL's media; `name`, `can_handle`, `fetch`), `AnalysisEngine`
  (`analyze_with_retry`, `analyze_captions`), `ObjectStore`, `JobQueue`,
  `SpendCap`, `DeviceTokenSigner`, `FreeRunAllowance`, `KeyVault`,
  `TokenVerifier`, `CapabilityProbe`, `ReleaseCatalog`, and `UploadedFile`
  (the shape of an incoming upload, so the use case never sees Starlette's
  class). These are structural (duck-typed) — an adapter satisfies a port
  just by having the right methods, no inheritance required.

**`application/`** — use cases: one class per user-facing operation,
orchestrating ports to do the work.
- `create_run.py` — `CreateRunUseCase`: validates terms accepted and
  exactly-one-source, admits the caller (`_admit`: BYOK, or a free run
  against a signed device token; the seam for future plan checks), spends
  the daily budget, saves/enqueues the run, and owns its own cleanup,
  including refunding the free run, if something fails partway through.
- `get_free_runs.py` — `GetFreeRunsUseCase`: a device's standing for today,
  issuing a token when needed. Read-only.
- `get_run.py` — `GetRunUseCase`: fetch + ownership check, plus the
  abandoned-run backstop: a `queued`/`processing` run whose `updated_at` is
  older than `WORKER_JOB_TIMEOUT_SECONDS + 120` is reported as failed and
  persisted that way, so a worker that died without writing cannot leave a
  run polling forever.
- `list_runs.py` — `ListRunsUseCase` (no staleness check: a listing must
  stay a read).
- `get_capabilities.py` — `GetCapabilitiesUseCase`: runs every probe, reports
  the worst state, never raises, and caches for a few seconds so an
  unauthenticated endpoint cannot be used to spawn subprocesses at will.
- `get_releases.py` — `GetReleasesUseCase`: the release index, cached five
  minutes, serving the last good answer when GitHub fails.
- `process_run.py` — `ProcessRunUseCase`: download/validate → normalize →
  analyze → persist. For a URL whose every resolver failed it tries the
  subtitle track first (`_analyze_captions`) and completes the run as
  `captions_only` if that works, otherwise re-raises the original download
  error. Runs the poster capture (`describe_visuals`) concurrently, persists
  `SourceMetadata` as soon as the download returns, masks unexpected
  exceptions behind a fixed message, handles arq's cancellation, and in
  `finally` releases the run's held free run (refunding it only when a link
  run was rejected before analysis) and deletes the S3 object and run
  directory. Run by both the in-process local runner and the arq worker — it
  doesn't know or care which. See `docs/backend/run-processing.md`.

**`infrastructure/`** — concrete adapters implementing the ports above.
Every adapter takes `Settings` in its constructor instead of importing a
global (this is what makes them independently testable — see
`backend/tests/`).
- `persistence/run_repository.py` — `RunStore`: Redis-backed in distributed
  mode, an in-process dict otherwise; entries expire `RUN_TTL_SECONDS` after
  the last write. Implements `RunRepository`.
- `media/service.py` — `MediaService`, the one `MediaProcessor` adapter,
  composing: `media/ffmpeg.py` (probe, duration cap, normalize),
  `media/uploads.py` (run directories and saved uploads),
  `media/resolvers/` (`ResolverChain` over `YtDlpResolver`, which wraps
  `media/ytdlp_downloader.py` and is the primary path for every URL, then
  `DirectHttpResolver`, a stdlib GET for links that name a media file
  outright; order is set here and is the contract), `media/captions.py` (the
  subtitle salvage path), `media/thumbnails.py` (the history poster: the
  publisher's thumbnail fetched through the SSRF guard, else a frame from the
  file; never raises), and `media/net.py` (`validate_public_url` and the
  shared outbound-fetch rules, deliberately the single SSRF guard every
  resolver and the thumbnail fetch go through).
- `ai/gemini_engine.py` — `GeminiEngine`, implements `AnalysisEngine`:
  upload, structured-output analysis with full-jitter retries on 429/5xx,
  the optional fallback model, and the text-only caption analysis.
  `ai/source_context.py` turns `SourceMetadata` into a fenced prompt block
  labelled as untrusted third-party text; pure string work, tested without an
  SDK.
- `storage/s3_object_store.py` — `S3ObjectStore`, implements `ObjectStore`
  (`S3_ADDRESSING_STYLE` picks path vs virtual-hosted URLs).
- `queue/job_queue.py` — `RunQueue`: dispatches to arq/Redis in distributed
  mode, or an in-process `asyncio` task otherwise (holding a reference so the
  task cannot be garbage-collected mid-run). Implements `JobQueue`.
- `quota/daily_budget.py` — `DailyBudget`, implements `SpendCap`.
- `quota/device_tokens.py` — `HmacDeviceTokens`, implements
  `DeviceTokenSigner`: stateless `<id>.<HMAC>` tokens; `validate_configuration`
  refuses to start a distributed deployment without `DEVICE_TOKEN_SECRET`.
- `quota/free_run_allowance.py` — `FreeRunAllowanceStore`, implements
  `FreeRunAllowance` (Redis Lua or an in-process dict; per-device and per-IP
  counters, plus the per-run hold/release that makes refunds possible).
- `byok/key_vault.py` — `ByokKeyStore`, implements `KeyVault`.
- `auth/jwt_verifier.py` — `JwtVerifier`, implements `TokenVerifier`.
- `health/probes.py` — one `CapabilityProbe` per dependency (`media_tools`,
  `url_download`, `analysis_engine`, `run_store`, `object_storage`,
  `daily_budget`), each exercising its dependency where that is cheap and
  side-effect free, and saying `probed=False` where it is not.
- `releases/github_releases.py` — `GithubReleaseCatalog`, implements
  `ReleaseCatalog`: reads GitHub Releases server-side with `GITHUB_TOKEN`
  and parses `v<version>-build<code>` tags (optionally `dev-` prefixed, for
  builds 1-30).
- `config.py` (`Settings`, plus `NATIVE_APP_ORIGINS`, the Capacitor
  WebView origins allowed unconditionally) and `logging_config.py`.

**`interface/`** — the only layer allowed to know about FastAPI/arq
directly.
- `api/app.py` — FastAPI app factory: lifespan (tool and temp-dir
  validation, device-token check, Redis ping, the `ALLOWED_ORIGINS="*"`
  warning, shutdown), CORS (with `Retry-After` exposed), rate-limit
  middleware, error handler registration, router mount.
- `api/routes.py` — thin route handlers. Each one extracts what it needs
  from the request, calls exactly one use case via `container`, and returns
  a response — no business logic lives here. Endpoints: `/api/health`,
  `/api/readiness`, `/api/capabilities`, `/api/releases`, `/api/free-runs`,
  `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{run_id}`.
- `api/schemas.py` — API response DTOs (`RunCreateResponse`,
  `RunStatusResponse`, `RunSummary`, `RunListResponse`,
  `FreeRunsResponse`). Deliberately *not* merged with `domain.entities.Run`
  — the API response never exposes `owner_id`. `CapabilityReport` and
  `ReleaseIndex` are returned directly; they carry nothing private.
- `api/dependencies.py` — `get_principal`: the one place that turns request
  headers into a `Principal`, using the injected `TokenVerifier` port for
  bearer tokens.
- `api/error_handlers.py` — maps each domain exception to its HTTP status
  code (400 for validation and terms, 401 device token, 402 free runs, 404,
  429 rate limit, 503 quota/scheduling/analysis unavailable), adds
  `Retry-After` where the error carries one, registered once via
  `app.add_exception_handler`.
- `api/rate_limiter.py` — slowapi `Limiter` setup, `client_ip`, `quota_key`.
  Not behind a port: there is only one implementation and no business rule
  to protect from framework leakage, so a port here would be pure ceremony.
  (It is also the one place a module-level `settings` is read at import
  time; see `docs/engineering-standards.md`.)
- `worker/settings.py` — the arq `WorkerSettings` plus its `startup`/
  `shutdown`/`process_run` job function, all backed by `container`.
  `process_run` takes the BYOK key out of the vault before calling the use
  case, so the key is never an arq job argument.

**`container.py`** — the composition root. Builds every adapter once and
wires them into the use cases; also fixes the order of the capability probes
and (inside `MediaService`) the resolver chain. It's the only file allowed to
import from every layer at once; nothing in `domain/` or `application/` ever
imports from it. `app/main.py` and `app/worker.py` are one-line re-export
shims (`from .interface.api.app import app` / `from .interface.worker.settings
import WorkerSettings`) so `Dockerfile`, `docker-compose.yml`, and
`railway.worker.json` — which reference `app.main:app` and
`app.worker.WorkerSettings` — needed no changes.

## Things kept intentionally simple

- **`VideoAnalysis`/`TranscriptSegment`/`ScreenTextSegment`/`RunStatus`
  live in `domain/entities.py`, not duplicated as separate API DTOs.**
  They're already framework-agnostic Pydantic models used identically by
  Gemini's structured-output schema, Redis persistence, and the API
  response — a parallel DTO would be pure duplication. The one thing kept
  *off* `VideoAnalysis` is `AnalysisCompleteness`, precisely because that
  model is handed to Gemini as its response schema.
- **One `MediaProcessor` port, not six.** FFmpeg, uploads, the resolvers,
  captions, thumbnails and the network guard stay as separate modules (each
  owns one concern), but `ProcessRunUseCase` and `CreateRunUseCase` only
  ever need them together in sequence, so `MediaService` composes them into
  a single adapter rather than forcing six constructor dependencies
  everywhere. `SourceResolver` is the one sub-port that is exposed, because
  adding a route to a URL's media is the change that happens most often.
- **Errors carry two messages.** `UserFacingError.log_detail` is how a
  phone-readable sentence and an operator-only diagnosis travel together
  without either leaking into the other's channel (`docs/error-messaging.md`).

## Adding something new

- **New business rule for creating/reading runs** → edit the relevant
  `application/*.py` use case. It only sees ports, so nothing there needs
  to know whether run storage is Redis or in-memory.
- **New storage backend / swap Gemini for another model** → write a new
  adapter in `infrastructure/` that satisfies the matching `domain.ports`
  Protocol, then point `container.py` at it. Nothing in `application/` or
  `interface/` changes.
- **New way to fetch a URL's media** → a `SourceResolver` in
  `media/resolvers/`, added to the chain in `MediaService.__init__`. It must
  route every outbound request through `media/net.py`.
- **New dependency worth reporting** → a `CapabilityProbe` in
  `health/probes.py`, appended to the list in `container.py`.
- **New HTTP endpoint** → add a route in `interface/api/routes.py` that
  calls a use case (new or existing) and returns a schema from
  `interface/api/schemas.py`.

## Tests

`backend/tests/` mirrors `backend/app/`: `tests/domain/`,
`tests/application/` (use-case tests against the fakes in
`tests/application/fakes.py`), `tests/infrastructure/<adapter>/`,
`tests/interface/api/`. Each adapter test constructs its class directly with
an explicit `Settings(...)` instead of monkeypatching a module-level global,
since every adapter takes its config as a constructor argument. 398 tests as
of 2026-11-07, all unit tests; there is no end-to-end run test, and
`key_vault.py`, `gemini_engine.py`'s network path and `s3_object_store.py`'s
real client remain covered by code review only (`docs/engineering-standards.md`).

## Changelog

- 2026-11-07 · main session · refreshed against the tree: added the resolver chain, captions, thumbnails, net guard, probes, releases, free-run and device-token adapters, the capability/release use cases, the full error and endpoint lists, and `tests/application/`
