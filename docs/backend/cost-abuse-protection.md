# Cost & abuse protection

Three independent layers bound how much this app can spend on Gemini calls, since there are no accounts or billing gates.

**Files**
- `backend/app/infrastructure/quota/daily_budget.py` — `DailyBudget`, implements `SpendCap`.
- `backend/app/interface/api/rate_limiter.py` — the slowapi `Limiter`, `client_ip`, `quota_key`.
- `backend/app/domain/policies.py` — `quota_key_from_headers` (pure function, no I/O — this is what `rate_limiter.py`'s `quota_key` calls).

**Layer 1 — per-IP/token rate limit** (`RATE_LIMIT_PER_HOUR`, default 20/hour): applied to `POST /api/runs` via `@limiter.limit(...)`. The rate-limit *key* is derived by `quota_key_from_headers`: a `Bearer` token hashes to `token:{sha256[:32]}` (never logs/stores the raw token), otherwise falls back to `ip:{client_ip}`, or `"anonymous"` if no IP is available. `client_ip` prefers `X-Forwarded-For` (first entry) over the raw socket peer, since deployment targets (Railway) sit behind a proxy. Redis-backed when `REDIS_URL` is set (holds across worker replicas), otherwise in-memory (single process only).

**Layer 2 — global daily cap** (`DAILY_RUN_CAP`, default 200): `DailyBudget.try_consume()`, keyed by UTC date (`videolens:runs:{YYYY-MM-DD}`), same Redis-or-memory duality as everything else here. This is the backstop for when abuse is spread across many IPs, which the per-IP limit alone can't stop. `daily_run_cap <= 0` disables it entirely.

**Layer 3 — BYOK exemption is asymmetric by design**: a bring-your-own-key run skips the daily cap (`CreateRunUseCase` never calls `try_consume()` when a key is present — that cap only protects the *shared* key's spend) but is **still** subject to the per-IP rate limit, since FFmpeg/bandwidth/worker capacity are spent either way regardless of whose Gemini key pays for the API call.

**Known issue**: none — this is a deliberately layered design and the trade-offs (documented in code comments already) look sound. The one thing worth knowing operationally: none of these layers replace setting a hard budget alert directly on the Gemini API key itself in Google Cloud/AI Studio — that's the only backstop enforced completely outside this app's own code (see root `README.md`, "Cost protection").

**Tests**: `backend/tests/infrastructure/quota/test_daily_budget.py` (local-mode cap logic), `backend/tests/interface/api/test_rate_limiter.py` (`client_ip` only), `backend/tests/domain/test_policies.py` (`quota_key_from_headers`).

## Changelog

- 2026-08-21 · main session · rate-limit responses now carry `detail` like every other error (slowapi's stock `error` key meant the UI showed a bare 429 fallback), and the daily-cap message points at BYOK
