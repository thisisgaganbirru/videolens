# Backend architecture

Clean architecture, dependencies pointing inward. Nothing in `domain/` or
`application/` imports FastAPI, Redis, boto3, or any other driver.

```
domain  <-  application  <-  infrastructure
                         <-  interface (api, worker)
```

`interface/` and `infrastructure/` never import each other; `container.py`
wires them. (Three known violations are recorded in
`docs/engineering-standards.md`.) Every adapter takes `Settings` in its
constructor, which is what makes it testable with an explicit `Settings(...)`.

## Codemap (`backend/app/`)

**`domain/`** — pure types and rules, no I/O.
`entities.py` (`Run`, `VideoAnalysis`, `SourceMetadata`, `CaptionTrack`,
`MediaVisuals`, capability and release models, free-run models, `Principal`),
`errors.py` (every exception a use case may raise; `UserFacingError` carries a
user message plus operator-only `log_detail`), `policies.py` (quota key,
client IP from the proxy-written `X-Forwarded-For` entry, client-id
validity, run staleness), `run_facts.py` (the media facts a history
card shows, derived from a stored run), `ports.py` (the `Protocol`s below).

**`application/`** — one use case per operation, orchestrating ports.
`create_run` (validate, admit via BYOK or a free run, spend the daily budget,
save, enqueue, clean up and refund on partial failure), `process_run` (the
pipeline: fetch → normalize → analyze → persist, with the caption-only fallback
and the concurrent poster capture; identical under the local runner and the
arq worker), `get_run` (ownership plus the abandoned-run backstop),
`list_runs`, `get_free_runs`, `get_capabilities`, `get_releases`.

**`infrastructure/`** — one adapter per port.

| Port | Adapter | Notes |
|---|---|---|
| `RunRepository` | `persistence/run_repository.py` | Redis or in-process dict; entries expire `RUN_TTL_SECONDS` after the last write |
| `MediaProcessor` | `media/service.py` | Composes `ffmpeg.py`, `uploads.py`, the resolver chain, `captions.py`, `thumbnails.py` |
| `SourceResolver` | `media/resolvers/` | Ordered chain, set in `MediaService`: `YtDlpResolver` (primary, wraps `ytdlp_downloader.py`) then `DirectHttpResolver` |
| — | `media/net.py` | `validate_public_url` and the shared fetch rules: the single SSRF guard every outbound request uses |
| `AnalysisEngine` | `ai/gemini_engine.py` | Upload, structured output, jittered retries, optional fallback model, caption-only analysis; `ai/source_context.py` fences publisher metadata as untrusted text |
| `ObjectStore` | `storage/s3_object_store.py` | |
| `JobQueue` | `queue/job_queue.py` | arq/Redis, or an in-process task it keeps a reference to |
| `SpendCap` | `quota/daily_budget.py` | |
| `DeviceTokenSigner` | `quota/device_tokens.py` | Stateless HMAC tokens; refuses to start distributed without a secret |
| `FreeRunAllowance` | `quota/free_run_allowance.py` | Per-device and per-IP counters, hold/release for refunds |
| `KeyVault` | `byok/key_vault.py` | Single-use, deleted on read, 15-minute TTL |
| `TokenVerifier` | `auth/jwt_verifier.py` | |
| `CapabilityProbe` | `health/probes.py` | One per dependency; `probed=False` where a check would cost money |
| `ReleaseCatalog` | `releases/github_releases.py` | Server-side GitHub read; parses `v<version>-build<code>` tags |

Plus `config.py` (`Settings`; `NATIVE_APP_ORIGINS` is the Capacitor WebView
origin allowed in code) and `logging_config.py`.

**`interface/`** — the only layer that knows FastAPI and arq.
`api/app.py` (factory, lifespan checks, CORS, rate-limit middleware),
`api/routes.py` (thin handlers: health, readiness, capabilities, releases,
free-runs, runs), `api/schemas.py` (response DTOs; kept separate from
`domain.entities.Run` so `owner_id` never leaks), `api/dependencies.py`
(`get_principal`), `api/error_handlers.py` (exception → status, `Retry-After`),
`api/rate_limiter.py` (slowapi; not behind a port, and the one import-time
global; the client IP comes from `policies.client_ip_from_forwarded` with
`TRUSTED_PROXY_HOPS`), `api/security_headers.py` (pure-ASGI middleware,
added last so every response, preflights and refusals included, carries the
hardening headers), `worker/settings.py` (arq `WorkerSettings`; takes the BYOK key out of
the vault before calling the use case).

**`container.py`** — composition root. Builds every adapter once, wires the
use cases, fixes the probe order. `app/main.py` and `app/worker.py` are
one-line shims so the Dockerfile, compose file and Railway configs reference
`app.main:app` / `app.worker.WorkerSettings`.

## Invariants

- A BYOK key never becomes an arq job argument, a stored field, or a log line.
- Every outbound fetch for a URL run goes through `media/net.py`, which
  resolves the host once and connects to the checked address (no DNS
  rebinding between check and fetch).
- The client IP is never the first `X-Forwarded-For` entry; a distributed
  deployment refuses to start with `ALLOWED_ORIGINS=*`.
- `VideoAnalysis` is Gemini's response schema; server-known facts
  (`AnalysisCompleteness`) live beside it on the run, not inside it.
- A thumbnail, duration, metadata or refund failure never fails a healthy run.
- Unexpected pipeline exceptions are stored as one fixed message; the real
  cause goes to the worker log only.
- The run store is a delivery buffer, not a system of record; history is the
  browser's.
- `ListRunsUseCase` never writes; the staleness check lives in `get_run` only.

## Cross-cutting

- **Errors**: domain exceptions map to HTTP in `error_handlers.py` (400
  validation, 401 device token, 402 free runs, 404, 429 rate limit, 503
  quota/scheduling/analysis). `docs/error-messaging.md` covers wording.
- **Spend limits**: rate limit, free runs, daily cap, BYOK exemption, plus
  a looser per-IP limit on the read endpoints;
  `docs/backend/cost-abuse-protection.md` and `free-runs.md`.
- **Response headers**: `docs/backend/security-headers.md`.
- **Config**: `Settings` from the environment, defaults documented in
  `.env.example`. Distributed mode is `REDIS_URL` set, which also requires
  object storage and `DEVICE_TOKEN_SECRET`.
- **Tests**: `tests/` mirrors `app/`; use-case tests use the fakes in
  `tests/application/fakes.py`. All unit tests; no end-to-end run test yet.

## Adding something new

- Business rule → the `application/` use case; it only sees ports.
- Storage backend or model swap → a new adapter satisfying the port, pointed
  at from `container.py`.
- URL source → a `SourceResolver` in `media/resolvers/`, added to the chain.
- Dependency worth reporting → a `CapabilityProbe`, appended in `container.py`.
- Endpoint → a route in `routes.py` calling a use case, returning a schema.

## Changelog

- 2026-11-07 · main session · rewritten as a codemap; merged the security pass (`security_headers.py`, trusted-proxy client IP, read-endpoint limit, startup refusal on a CORS wildcard): port/adapter table, invariants, cross-cutting; covers the resolver chain, captions, probes, releases, free runs and device tokens
