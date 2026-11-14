# Backend architecture

Clean architecture, dependencies pointing inward. Nothing in `domain/` or
`application/` imports FastAPI, Redis, boto3, or any other driver.

```
domain  <-  application  <-  infrastructure
                         <-  interface (api, worker)
```

`interface/` and `infrastructure/` never import each other; `container.py`
wires them. (Two known violations remain, recorded in
`docs/engineering-standards.md`.) Every adapter takes `Settings` in its
constructor, which is what makes it testable with an explicit `Settings(...)`.

## Codemap (`backend/app/`)

**`domain/`** — pure types and rules, no I/O.
`entities.py` (`Run`, `VideoAnalysis`, `SourceMetadata`, `CaptionTrack`,
`MediaVisuals`, capability and release models, free-run models, `Principal` and `AuthMethod`, `Account`, `Workspace`,
`ApiKey`, the billing records), `entitlements.py` (`Plan.FREE` / `Plan.PAID`, `Entitlement`, `MediaTier`),
`errors.py` (every exception a use case may raise; `UserFacingError` carries a
user message plus operator-only `log_detail`), `policies.py` (quota key per principal, `can_access_run`, `looks_like_api_key`,
client IP from the proxy-written `X-Forwarded-For` entry, client-id
validity, run staleness), `run_facts.py` (the media facts a history
card shows, derived from a stored run), `ports.py` (the `Protocol`s below).

**`application/`** — one use case per operation, orchestrating ports.
`create_run` (validate, admit via BYOK, an account free run (signed in) or a device free run, spend the daily budget,
save, enqueue, clean up and refund on partial failure), `process_run` (the
pipeline: fetch → normalize → analyze → persist, with the caption-only fallback
and the concurrent poster capture; identical under the local runner and the
arq worker), `get_run` (ownership plus the abandoned-run backstop),
`list_runs`, `get_free_runs`, `get_capabilities`, `get_releases`,
`identify_caller` (API key, then bearer token, then client id → `Principal`),
`get_account` + `entitlements`, and the API-key use cases (`create_api_key`,
`list_api_keys`, `revoke_api_key`, gated by `api_key_access`). The paid plan:
`billing` (`BillingPlans`: is this account paid now; `ExtraRunBilling`:
held -> due -> reported, billed once on success), `get_billing`,
`start_checkout`, `open_billing_portal`, `handle_billing_webhook`
(`docs/backend/billing.md`).

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
| `AccountFreeRunAllowance` | `persistence/account_free_runs.py` | Signed-in free runs per account per UTC day, and the paid plan's included runs per UTC month, on separate keys (SQL upsert-if-below-limit, or in-memory), hold/release like the device one |
| `KeyVault` | `byok/key_vault.py` | Single-use, deleted on read, 15-minute TTL |
| `TokenVerifier` | `auth/jwt_verifier.py` | RS256/ES256, required `exp`/`iat`/`sub`, 30 s leeway, audience when set; one caching JWKS client |
| `AccountDirectory` | `persistence/account_directory.py` | SQL (Postgres via asyncpg, SQLite in tests) or in-memory; disabled in distributed mode without `DATABASE_URL` |
| `ApiKeyRepository` | `persistence/api_key_repository.py` | SHA-256 only, cap enforced in the insert transaction, `last_used_at` at most once a minute |
| `IdentityProviderUsers` | `persistence/identity_users.py` | Whether Supabase still has a user (`auth_user_exists`); asked on first sight of a subject and before key issue, so a token that outlived its deleted user cannot re-create rows. SQLite and in-memory: always yes |
| `AccountDeleter` | `persistence/account_deleter.py` | Account deletion: identity rows in one transaction, then the Supabase user via the `SECURITY DEFINER` function from `0002_auth_user_deleter` (skipped on SQLite and in memory) |
| — | `persistence/database.py`, `schema.py` | One async engine; schema owned by Alembic (`backend/migrations/`, a release step) |
| `BillingGateway` | `billing/stripe_gateway.py` | Stripe-hosted Checkout and Portal, Price reads (cached), webhook signature check, subscription re-fetch, cancel, meter events (identifier = run id); stripe-python `StripeClient` in a thread; off unless `STRIPE_*` is set |
| `BillingAccounts`, `ExtraRunLedger` | `persistence/billing_store.py` | SQL (migration `0004_billing`) or in-memory (local only); conditional `held -> due` / `held -> void` writes make billing exactly-once |
| `CapabilityProbe` | `health/probes.py` | One per dependency (`auth` the seventh, `database` the eighth, `billing` the ninth); `probed=False` where a check would cost money |
| `ReleaseCatalog` | `releases/github_releases.py` | Server-side GitHub read; parses `v<version>-build<code>` tags |

Plus `config.py` (`Settings`; `NATIVE_APP_ORIGINS` is the Capacitor WebView
origin allowed in code) and `logging_config.py`.

**`interface/`** — the only layer that knows FastAPI and arq.
`api/app.py` (factory, lifespan checks, CORS, rate-limit middleware),
`api/routes.py` (thin handlers: health, readiness, capabilities, releases,
free-runs, runs, `/api/me`, `/api/keys`, `/api/billing*`), `api/schemas.py` (response DTOs; kept separate from
`domain.entities.Run` so `owner_id` never leaks), `api/dependencies.py`
(`get_principal`, `get_signed_in_principal`, `require_person`), `api/error_handlers.py` (exception → status, `Retry-After`),
`api/rate_limiter.py` (slowapi; not behind a port, and the one import-time
global; the client IP comes from `policies.client_ip_from_forwarded` with
`TRUSTED_PROXY_HOPS`), `api/security_headers.py` (pure-ASGI middleware,
added last so every response, preflights and refusals included, carries the
hardening headers), `worker/settings.py` (arq `WorkerSettings`; takes the BYOK key out of
the vault before calling the use case; cron `flush_extra_runs` every 10 minutes).

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
- An extra run is billed only after its result is stored, at most once; a
  billing failure never fails a run, and a Stripe type never leaves
  `infrastructure/billing/`.

## Cross-cutting

- **Errors**: domain exceptions map to HTTP in `error_handlers.py` (400
  validation, 401 device token / authentication, 402 free runs, 403 forbidden,
  404, 409 API-key cap, 429 rate limit, 503 quota/scheduling/analysis/auth
  not configured). `docs/error-messaging.md` covers wording.
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
- 2026-11-08 · backend subagent (auth phase 1) · added the identity slice: `identify_caller` and the account/API-key use cases, `AccountDirectory` and `ApiKeyRepository` ports with SQL and in-memory adapters, `database.py`/`schema.py` and Alembic, the `auth` probe, the new routes and dependencies; layering violations down to two
- 2026-11-09 · backend subagent (auth phase 3) · added the `AccountDeleter` port and adapters, `RunRepository.delete_for_owner`, `DeleteAccountUseCase` (`DELETE /api/me`) and the `database` probe
- 2026-11-09 · backend subagent (auth phase 3, review fix) · added the `IdentityProviderUsers` port and adapters
- 2026-11-13 · backend agent · `AccountFreeRunAllowance` port and adapters; `create_run` admits signed-in accounts against their monthly allowance
- 2026-11-13 · backend agent · paid plan: `BillingGateway` (Stripe) and `BillingAccounts`/`ExtraRunLedger` ports and adapters, the billing use cases, paid admission in `create_run`, billing on completion in `process_run`, the `billing` probe, `flush_extra_runs` cron
- 2026-11-14 · backend agent · `AccountFreeRunAllowance` takes `period` (`FreeRunPeriod` day/month); free accounts count per UTC day, the paid plan per month
