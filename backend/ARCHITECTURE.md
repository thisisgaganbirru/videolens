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
only in `container.py`.

## Layers

**`domain/`** — pure business types and rules, no I/O.
- `entities.py` — `Run`, `VideoAnalysis`, `TranscriptSegment`,
  `ScreenTextSegment`, `RunStatus`, `Principal`, `SavedUpload`.
- `errors.py` — the exceptions a use case can raise: `MediaValidationError`,
  `TermsNotAcceptedError`, `InvalidSourceError`, `QuotaExceededError`,
  `RunSchedulingError`, `RunNotFoundError`, `GeminiConfigurationError`.
- `policies.py` — pure functions/constants that encode a business rule
  without needing any infrastructure: `quota_key_from_headers`,
  `is_valid_client_id`.
- `ports.py` — `Protocol` interfaces the application layer depends on:
  `RunRepository`, `MediaProcessor`, `AnalysisEngine`, `ObjectStore`,
  `JobQueue`, `SpendCap`, `KeyVault`, `TokenVerifier`, `UploadedFile`.
  These are structural (duck-typed) — an adapter satisfies a port just by
  having the right methods, no inheritance required.

**`application/`** — use cases: one class per user-facing operation,
orchestrating ports to do the work. This is where the business rules that
used to live inline in `main.py`/`pipeline.py` now live.
- `create_run.py` — `CreateRunUseCase`: validates terms accepted and
  exactly-one-source, spends the daily budget, saves/enqueues the run, and
  owns its own cleanup if something fails partway through.
- `get_run.py` — `GetRunUseCase`: fetch + ownership check.
- `list_runs.py` — `ListRunsUseCase`.
- `process_run.py` — `ProcessRunUseCase`: download/validate → normalize →
  analyze → persist. Run by both the in-process local runner and the arq
  worker — it doesn't know or care which.

**`infrastructure/`** — concrete adapters implementing the ports above.
Every adapter takes `Settings` in its constructor instead of importing a
global (this is what makes them independently testable — see
`backend/tests/`).
- `persistence/run_repository.py` — `RunStore`: Redis-backed in distributed
  mode, an in-process dict otherwise. Implements `RunRepository`.
- `media/{ffmpeg,ytdlp_downloader,uploads}.py` — FFmpeg probing/normalizing,
  yt-dlp downloading, and upload/run-dir handling. `media/service.py`'s
  `MediaService` composes all three into one `MediaProcessor` adapter,
  since `ProcessRunUseCase` always uses them together in sequence.
- `ai/gemini_engine.py` — `GeminiEngine`, implements `AnalysisEngine`.
- `storage/s3_object_store.py` — `S3ObjectStore`, implements `ObjectStore`.
- `queue/job_queue.py` — `RunQueue`: dispatches to arq/Redis in distributed
  mode, or an in-process `asyncio` task otherwise. Implements `JobQueue`.
- `quota/daily_budget.py` — `DailyBudget`, implements `SpendCap`.
- `byok/key_vault.py` — `ByokKeyStore`, implements `KeyVault`.
- `auth/jwt_verifier.py` — `JwtVerifier`, implements `TokenVerifier`.
- `config.py`, `logging_config.py` — settings and log formatting, unchanged
  from before the refactor except for their new location.

**`interface/`** — the only layer allowed to know about FastAPI/arq
directly.
- `api/app.py` — FastAPI app factory: lifespan (tool validation, startup
  checks, shutdown), CORS, rate-limit middleware, error handler
  registration, router mount.
- `api/routes.py` — thin route handlers. Each one extracts what it needs
  from the request, calls exactly one use case via `container`, and returns
  a response — no business logic lives here anymore.
- `api/schemas.py` — API response DTOs (`RunCreateResponse`,
  `RunStatusResponse`, `RunSummary`, `RunListResponse`). Deliberately *not*
  merged with `domain.entities.Run` — the API response never exposes
  `owner_id`.
- `api/dependencies.py` — `get_principal`: the one place that turns request
  headers into a `Principal`, using the injected `TokenVerifier` port for
  bearer tokens.
- `api/error_handlers.py` — maps each domain exception to its HTTP status
  code, registered once via `app.add_exception_handler`.
- `api/rate_limiter.py` — slowapi `Limiter` setup. Not behind a port: there
  is only one implementation and no business rule to protect from framework
  leakage, so a port here would be pure ceremony.
- `worker/settings.py` — the arq `WorkerSettings` plus its `startup`/
  `shutdown`/`process_run` job function, all backed by `container`.

**`container.py`** — the composition root. Builds every adapter once and
wires them into the use cases. It's the only file allowed to import from
every layer at once; nothing in `domain/` or `application/` ever imports
from it. `app/main.py` and `app/worker.py` are one-line re-export shims
(`from .interface.api.app import app` / `from .interface.worker.settings
import WorkerSettings`) so `Dockerfile`, `docker-compose.yml`, and
`railway.worker.json` — which reference `app.main:app` and
`app.worker.WorkerSettings` — needed no changes.

## Two things kept intentionally simple

- **`VideoAnalysis`/`TranscriptSegment`/`ScreenTextSegment`/`RunStatus`
  live in `domain/entities.py`, not duplicated as separate API DTOs.**
  They're already framework-agnostic Pydantic models used identically by
  Gemini's structured-output schema, Redis persistence, and the API
  response — a parallel DTO would be pure duplication.
- **One `MediaProcessor` port, not three.** `ffmpeg.py`, `ytdlp_downloader.py`,
  and `uploads.py` stay as separate modules (each owns one concern), but
  `ProcessRunUseCase` and `CreateRunUseCase` only ever need them together in
  sequence, so `MediaService` composes them into a single adapter rather
  than forcing three separate constructor dependencies everywhere.

## Adding something new

- **New business rule for creating/reading runs** → edit the relevant
  `application/*.py` use case. It only sees ports, so nothing there needs
  to know whether run storage is Redis or in-memory.
- **New storage backend / swap Gemini for another model** → write a new
  adapter in `infrastructure/` that satisfies the matching `domain.ports`
  Protocol, then point `container.py` at it. Nothing in `application/` or
  `interface/` changes.
- **New HTTP endpoint** → add a route in `interface/api/routes.py` that
  calls a use case (new or existing) and returns a schema from
  `interface/api/schemas.py`.

## Tests

`backend/tests/` mirrors `backend/app/`: `tests/domain/`,
`tests/infrastructure/<adapter>/`, `tests/interface/api/`. Each adapter
test constructs its class directly with an explicit `Settings(...)` instead
of monkeypatching a module-level global, since every adapter now takes its
config as a constructor argument.
