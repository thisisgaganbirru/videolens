# Cost & abuse protection

Three independent layers bound how much this app can spend on Gemini calls, since there are no accounts or billing gates.

**Files**
- `backend/app/infrastructure/quota/daily_budget.py` — `DailyBudget`, implements `SpendCap`.
- `backend/app/interface/api/rate_limiter.py` — the slowapi `Limiter`, `client_ip`, `quota_key`.
- `backend/app/domain/policies.py` — `quota_key_from_headers` (pure function, no I/O — this is what `rate_limiter.py`'s `quota_key` calls).

**Layer 1 — per-IP/token rate limit** (`RATE_LIMIT_PER_HOUR`, default 20/hour): applied to `POST /api/runs` via `@limiter.limit(...)`. The rate-limit *key* is derived by `quota_key_from_headers`: a `Bearer` token hashes to `token:{sha256[:32]}` (never logs/stores the raw token), otherwise falls back to `ip:{client_ip}`, or `"anonymous"` if no IP is available. `client_ip` reads `X-Forwarded-For` through `policies.client_ip_from_forwarded`: the client is the entry `TRUSTED_PROXY_HOPS` (default 2) from the **end** of the header, i.e. the number of trailing entries the deployment's own proxies write. Until 2026-11-07 it took the *first* entry, which is whatever the client put there, so a forged header picked a fresh rate-limit bucket (and a fresh free-run IP bucket) per request. `0` ignores the header and uses the socket peer; with no header at all (local, docker compose, direct) the peer is used anyway.

**What Railway sends** (measured on dev, 2026-11-07, with a temporary opt-in diagnostic, PR #116): the edge **replaces** `X-Forwarded-For` with `<client>, <edge hop>`. A client-sent `X-Forwarded-For` never arrives. The edge hop is a Railway address that changes between requests (`152.233.40.1`, `152.233.40.2`, ...), and the socket peer is a different `100.64.0.x` each time. `X-Real-IP` is also overwritten with the client. `Forwarded` and `X-Envoy-External-Address` pass through from the client untouched, so they must never be trusted. With the earlier default of 1 the key was the edge hop, so every request landed in its own bucket and no per-IP limit tripped on Railway (135 reads in 30 s, no 429). Hence 2. If Railway ever changes this shape, re-measure: send a request with a forged `X-Forwarded-For` and `X-Real-IP` and log what reaches the app. Redis-backed when `REDIS_URL` is set (holds across worker replicas), otherwise in-memory (single process only).

**Layer 2 — global daily cap** (`DAILY_RUN_CAP`, default 200): `DailyBudget.try_consume()`, keyed by UTC date (`videolens:runs:{YYYY-MM-DD}`), same Redis-or-memory duality as everything else here. This is the backstop for when abuse is spread across many IPs, which the per-IP limit alone can't stop. `daily_run_cap <= 0` disables it entirely.

**Layer 3 — BYOK exemption is asymmetric by design**: a bring-your-own-key run skips the daily cap (`CreateRunUseCase` never calls `try_consume()` when a key is present — that cap only protects the *shared* key's spend) but is **still** subject to the per-IP rate limit, since FFmpeg/bandwidth/worker capacity are spent either way regardless of whose Gemini key pays for the API call.

**Layer 1b — read endpoints** (`READ_RATE_LIMIT_PER_MINUTE`, default 120/minute, same per-IP key): `GET /api/runs/{id}`, `GET /api/runs` and `GET /api/free-runs` were unlimited until 2026-11-07. They spend no Gemini budget, but each is a Redis round trip and `free-runs` mints a signed device token for any caller without one, so a flood of either was free. The web app polls one run every 3 s, so 120/min leaves room for several tabs. `<= 0` disables (slowapi `exempt_when`). The limiter uses `key_style="endpoint"`: one bucket per route function and caller. slowapi's default (`"url"`) buckets by request path, so until 2026-11-07 every distinct `/api/runs/{run_id}` had its own bucket and a caller cycling ids was never limited (measured on Railway dev: 135 GETs to random ids, no 429, even after the hop fix).

**Layer 4: per-device free runs** (`FREE_RUNS_PER_DEVICE`, default 3/day, with a `FREE_RUNS_PER_IP` backstop of 10/day). This applies to non-BYOK callers only and is checked before Layer 2. It has its own doc: `free-runs.md`.

**Retry-After** (refinement 7): the two "come back later" refusals say when.
The domain errors carry `retry_after_seconds` and only the interface layer
turns it into a header (`error_handlers.retry_after_headers`); `Retry-After`
is in the CORS `expose_headers` (`app.py`), since it is not a safelisted
response header and a cross-origin `fetch` would otherwise read null.

- Layer 1, the 429: `app.py` `_rate_limited` builds a `RateLimitedError` whose
  seconds come from `rate_limiter.retry_after_seconds(request)`: the limit
  slowapi recorded on `request.state.view_rate_limit`, its window's reset time
  from `limiter.limiter.get_window_stats` (fixed window), rounded up, at least
  1. Any failure there (Redis blip, no recorded limit) means no header, never
  a 500. The frontend words it "Try again in about N minutes".
- Layer 2, the 503: `CreateRunUseCase` raises `QuotaExceededError` with the
  seconds until the next UTC midnight (`policies.seconds_until_next_utc_day`),
  when the day's key rolls over. The frontend shows the 503's `detail` and
  does not read the header today; it is there for any client that does.
- Layer 4 answers 402, not 429, and carries `resets_at` in `GET
  /api/free-runs` already; no header added.

**Known issue**: none — this is a deliberately layered design and the trade-offs (documented in code comments already) look sound. The one thing worth knowing operationally: none of these layers replace setting a hard budget alert directly on the Gemini API key itself in Google Cloud/AI Studio — that's the only backstop enforced completely outside this app's own code (see root `README.md`, "Cost protection").

**Tests**: `backend/tests/infrastructure/quota/test_daily_budget.py` (local-mode cap logic), `backend/tests/interface/api/test_rate_limiter.py` (`client_ip` with the measured Railway header shapes, forged headers included; the read limit tripping across random run ids), `backend/tests/domain/test_policies.py` (`quota_key_from_headers`, `seconds_until_next_utc_day`, `seconds_until`), `backend/tests/interface/api/test_retry_after.py` (header on 429/503, window read from a real in-memory limiter, failure degrades to no header, CORS exposes it).

## Changelog

- 2026-08-21 · main session · rate-limit responses now carry `detail` like every other error (slowapi's stock `error` key meant the UI showed a bare 429 fallback), and the daily-cap message points at BYOK
- 2026-11-01 · backend agent (Phase 5b) · added Layer 4: the per-device free-run allowance (see `free-runs.md`)
- 2026-11-02 · frontend agent (refinement 7) · 429 (rate limit) and 503 (daily cap) now send Retry-After: domain errors carry retry_after_seconds (new RateLimitedError; QuotaExceededError gains it), interface sets the header; CORS exposes Retry-After
- 2026-11-07 · security-check · `client_ip` trusts only the entry the deployment's proxies appended (`TRUSTED_PROXY_HOPS`, from the right; was the client-supplied first entry); read endpoints rate-limited (`READ_RATE_LIMIT_PER_MINUTE`)
- 2026-11-07 · general-purpose subagent (dispatched by videolens-9f) · `TRUSTED_PROXY_HOPS` default 1 → 2: Railway's edge writes `X-Forwarded-For: <client>, <edge hop>` with a varying edge hop, so the per-IP limits never tripped on Railway; measured shapes documented and tested
- 2026-11-07 · general-purpose subagent (dispatched by videolens-9f) · limiter `key_style="endpoint"`: the read limit on `GET /api/runs/{run_id}` was bucketed per path (per run id), so it never tripped for a caller cycling ids
