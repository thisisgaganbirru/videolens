# Free runs (per-device daily allowance)

Callers without their own Gemini key get `FREE_RUNS_PER_DEVICE` runs per UTC day (default 3), counted against a signed, anonymous device token, with `FREE_RUNS_PER_IP` (default 10) per client IP as a backstop. Callers who send `X-Gemini-Api-Key` are exempt, the same way they are exempt from `DAILY_RUN_CAP`. This sits on top of the other limits in `cost-abuse-protection.md` and does not replace any of them.

**Files**
- `backend/app/domain/ports.py`: `DeviceTokenSigner`, `FreeRunAllowance`.
- `backend/app/domain/entities.py`: `FreeRunStatus`, `FreeRunClaim`.
- `backend/app/domain/errors.py`: `DeviceTokenInvalidError` (401), `FreeRunsExhaustedError` (402, carries `limit`/`used`).
- `backend/app/infrastructure/quota/device_tokens.py`: `HmacDeviceTokens`, the token signer plus the startup check `validate_configuration()`.
- `backend/app/infrastructure/quota/free_run_allowance.py`: `FreeRunAllowanceStore`, the counters (Redis Lua or an in-process dict), plus `hold`/`release`, the per-run record that lets processing hand a run back.
- `backend/app/application/create_run.py`: `CreateRunUseCase._admit`, the check itself; `execute` places the hold.
- `backend/app/application/process_run.py`: `ProcessRunUseCase._settle_free_run`, the refund for a link run rejected before analysis (failed download or duration cap).
- `backend/app/application/get_free_runs.py`: `GetFreeRunsUseCase`.
- `backend/app/interface/api/routes.py`: `GET /api/free-runs`; `POST /api/runs` passes `X-Device-Token` and `client_ip(request)` (the rate limiter's IP extraction).
- `backend/app/interface/api/error_handlers.py`: the 401 and 402 bodies.
- `backend/app/interface/api/app.py`: CORS allows `X-Device-Token`; lifespan runs `validate_configuration()`.

## API contract

`GET /api/free-runs` reads an optional `X-Device-Token`. If the token is missing or its signature does not verify, the endpoint issues a new one. It is read-only and never spends a run. It needs no `X-Client-ID` and is not rate limited, because issuing a token is free and stateless.

```json
{"device_token": "<id>.<sig>", "enabled": true, "limit": 3, "used": 1, "remaining": 2, "resets_at": "2026-11-02T00:00:00Z"}
```

`enabled: false` means the allowance is off (`FREE_RUNS_PER_DEVICE <= 0`), so there is no limit and the client hides the banner. `limit`, `used` and `remaining` are then all 0. `used` is the device's own count only; the IP backstop is not reflected.

`POST /api/runs` applies the check only when no Gemini key is sent and the allowance is enabled:
- missing or invalid `X-Device-Token`: `401 {"detail": "...", "code": "device_token_invalid"}`. The client refetches a token and retries once.
- device or IP counter at its limit: `402 {"detail": "You have used your free runs. Add your own Gemini key to keep going.", "code": "free_runs_used", "limit": <device limit>, "used": <device used>}`. The body is the same whichever counter tripped.

Other errors keep the plain `{"detail"}` shape.

## Rules

- **Order in `CreateRunUseCase`:** terms, then exactly one source, then `_admit` (free run), then `DAILY_RUN_CAP`, then save/probe/upload/enqueue. Invalid requests never spend a free run, and nobody without a free run reaches the daily budget or FFmpeg. Before this change the daily cap ran *before* the source check; it now runs after it.
- **Refunds at intake:** any exception after `_admit` hands the run back (`FreeRunAllowance.refund(claim)`). That covers the daily cap rejecting, `MediaValidationError` (for example over the duration cap) and scheduling failures. The claim records its UTC day, so a refund after midnight goes to the right day, and a counter never drops below 0.
- **Refunds when a link run is rejected before analysis** (owner decisions, 2026-11-02: "refund the free run on failed downloads", then "yes refund the duration cap one too"): a link run turned away before any Gemini call gets its free run back. Two triggers, both tracked by the `rejected_before_analysis` flag in `ProcessRunUseCase.execute`:
  - **The download fails:** `MediaProcessor.download_url` raises (any exception, normally the `MediaValidationError` the yt-dlp adapter wraps every failure in, such as "This post isn't public") **and** the caption fallback does not complete the run.
  - **The downloaded file fails the duration cap:** `MediaProcessor.enforce_duration_cap` raises on the link path (too long, or ffprobe cannot read the duration). This mirrors intake, which already refunds over-long uploads. The cap is never checked on the caption-fallback path, so a run that reached Gemini through captions can never trigger it.

  Everything else during processing is **not** refunded: a caption fallback that reached Gemini and failed there, normalize, Gemini upload/analysis, cancellation (job timeout), and every failure of an uploaded file. That includes the worker's duration re-check of an S3 upload: uploads are length-checked, and refunded, at intake. A caption rescue completes the run, so it keeps its free run.
- **How the claim reaches processing:** after `_admit`, and before the job is enqueued, `CreateRunUseCase` calls `FreeRunAllowance.hold(run_id, claim)`. The store records the claim's resolved counter keys (day-scoped, IP already hashed), not the claim: Redis `videolens:free:held:{run_id}` (JSON list, 2-day TTL) in distributed mode, an in-process dict locally. Nothing new travels in job arguments (arq logs those) and nothing is added to `Run`, so nothing can leak through `api/schemas.py`. `ProcessRunUseCase` always calls `release(run_id, refund=rejected_before_analysis)` in its `finally`, which reads and deletes the hold in one `MULTI` (GET+DEL), then decrements those keys with the floor-at-0 refund script. Only the first release for a run finds the hold, so an arq retry or a second call can never refund twice. BYOK runs and runs with the allowance off never hold anything, so their release is a no-op. A failed intake drops the hold (`release(refund=False)`) before its own `refund(claim)`, for the same reason. Because the stored keys carry the claim's day, a refund after UTC midnight still goes to that day. A release that raises is logged and never changes the run's outcome; an unreleased hold just expires.
- **Atomicity (Redis):** one Lua script checks both counters and only then increments both (with a 2-day TTL), so a rejected request takes nothing and two racing requests cannot both take the last run. Keys: `videolens:free:device:{YYYY-MM-DD}:{device_id}` and `videolens:free:ip:{YYYY-MM-DD}:{sha256(ip)[:32]}`. The raw IP is never written.
- **No IP** (no forwarded header and no socket peer) means no IP backstop, rather than one shared bucket. The IP is the `X-Forwarded-For` entry the deployment's own proxy wrote for the client (`TRUSTED_PROXY_HOPS` from the right, 2 on Railway, see `cost-abuse-protection.md`), never the client-supplied first entry - a forged header used to reset this counter per request. Until 2026-11-07 the default of 1 picked Railway's per-request edge hop instead, so this backstop did not hold on Railway.
- **Token:** `<token_urlsafe(16)>.<base64url(HMAC-SHA256(secret, id))>`, checked with `hmac.compare_digest`. It is stateless, and any replica with the same secret verifies it.
- **Secret:** if `DEVICE_TOKEN_SECRET` is blank in local mode, a random key is generated per process and a warning is logged. If it is blank in distributed mode (`REDIS_URL` set) while the allowance is on, the API refuses to start, because replicas would reject each other's tokens. `docker-compose.yml` sets a local-only placeholder for this reason. Rotating the secret re-issues every device a token, so anonymous counts effectively reset.
- **MCP is unaffected:** BYOK is mandatory there, so every MCP call carries a key and skips this check entirely.
- **Seam for paid plans:** `_admit` is the single place that decides whether a caller may start a run on the shared key. A signed-in plan check belongs there.

## How easy is it to bypass

- **Clearing storage or a private window** gives a new device token and a fresh device count. This is bounded by the per-IP counter (10/day by default). `GET /api/free-runs` (which issues the token) is also rate-limited per IP since 2026-11-07 (`READ_RATE_LIMIT_PER_MINUTE`).
- **New IP** (VPN, toggling mobile data, another network) gives a fresh IP counter. Combined with clearing storage, that resets both counters. Nothing here stops a determined user with many IPs.
- **Forged or edited tokens** are rejected by the HMAC check. A client cannot invent device ids.
- **The global `DAILY_RUN_CAP`** still bounds total spend regardless of devices or IPs, and the per-IP `RATE_LIMIT_PER_HOUR` still applies.
- **False positives:** on shared networks (offices, campuses, carrier NAT) many people share one IP and can hit `FREE_RUNS_PER_IP` together. They see the same 402 and can add their own key.

The purpose is to stop casual overuse of the shared key, not to authenticate anyone.

**Tests**: `backend/tests/infrastructure/quota/test_device_tokens.py` (sign/verify/tamper, startup check), `backend/tests/infrastructure/quota/test_free_run_allowance.py` (per device, per IP, day keys, refund, read-only status; hold/release: refund on release, at most once, release without refund, nothing held, after-midnight day, no raw IP in the hold), `backend/tests/application/test_create_run.py` (`FreeRunAdmissionTests`, including the hold being placed, BYOK holding nothing, a rejected intake dropping the hold and refunding once), `backend/tests/application/test_process_run.py` (`FreeRunDownloadRefundTests`: download failure refunds, unexpected download error refunds, analyze failure does not, BYOK does not, no double refund on a retried job, caption rescue keeps it, captions failing at Gemini do not, duration cap after download refunds (once, and not for BYOK), an S3 upload over the cap in the worker does not, normalize after download does not, uploads do not, a failing release leaves the run outcome alone), `backend/tests/interface/api/test_free_run_routes.py` (GET endpoint, 401/402 bodies, CORS). The Redis Lua and `MULTI` paths have no automated test (there is no Redis in CI).

## Changelog
- 2026-11-01 · backend agent (Phase 5b) · created: per-device free-run allowance, `GET /api/free-runs`, 401/402 codes on `POST /api/runs`
- 2026-11-02 · backend agent (free-run download refund) · a link run whose download fails now gets its free run back: `FreeRunAllowance.hold`/`release`, held at intake, released in `ProcessRunUseCase`; other processing failures stay unrefunded
- 2026-11-02 · backend agent (duration-cap refund) · a link run that downloads but fails the duration cap now also gets its free run back; flag renamed `download_failed` → `rejected_before_analysis`; normalize, Gemini and upload failures stay unrefunded
- 2026-11-07 · security-check · IP backstop keyed on the proxy-appended X-Forwarded-For entry, not the client-supplied one; `GET /api/free-runs` rate-limited
- 2026-11-07 · general-purpose subagent (dispatched by videolens-9f) · IP backstop now holds on Railway: `TRUSTED_PROXY_HOPS` default 2 (Railway's edge writes `<client>, <edge hop>`)
