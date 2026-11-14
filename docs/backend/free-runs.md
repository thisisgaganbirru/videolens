# Free runs (per-device daily allowance, per-account daily allowance)

Callers without their own Gemini key get `FREE_RUNS_PER_DEVICE` runs per UTC day (default 3), counted against a signed, anonymous device token, with `FREE_RUNS_PER_IP` (default 10) per client IP as a backstop. Callers who send `X-Gemini-Api-Key` are exempt, the same way they are exempt from `DAILY_RUN_CAP`. This sits on top of the other limits in `cost-abuse-protection.md` and does not replace any of them.

**Signed-in callers** (owner decision 2026-11-13, "Level 1, signed in free"; made daily 2026-11-14) get `FREE_RUNS_PER_ACCOUNT_DAILY` runs per UTC day (default 10) counted against their **account** instead, so the runs follow the person across devices. It was 10 per calendar month until 2026-11-14; the owner changed it because 3 a day anonymous (about 90 a month) made signing in cut capacity. See "Signed-in free runs (account scope)" below. The paid plan's included runs stay monthly (`docs/backend/billing.md`).

**Files**
- `backend/app/domain/ports.py`: `DeviceTokenSigner`, `FreeRunAllowance`.
- `backend/app/domain/entities.py`: `FreeRunStatus`, `FreeRunClaim`.
- `backend/app/domain/errors.py`: `DeviceTokenInvalidError` (401), `FreeRunsExhaustedError` (402, carries `limit`/`used`/`scope`/`period`).
- `backend/app/infrastructure/quota/device_tokens.py`: `HmacDeviceTokens`, the token signer plus the startup check `validate_configuration()`.
- `backend/app/infrastructure/quota/free_run_allowance.py`: `FreeRunAllowanceStore`, the counters (Redis Lua or an in-process dict), plus `hold`/`release`, the per-run record that lets processing hand a run back.
- `backend/app/application/create_run.py`: `CreateRunUseCase._admit`, the check itself; `execute` places the hold.
- `backend/app/application/process_run.py`: `ProcessRunUseCase._settle_free_run`, the refund for a link run rejected before analysis (failed download or duration cap) or found already failed by the stale-run check.
- `backend/app/application/free_run_holds.py`: `settle_free_run_holds`, the one release helper the worker and `GetRunUseCase` share.
- `backend/app/application/get_run.py`: the stale-run check's refund.
- `backend/app/application/get_free_runs.py`: `GetFreeRunsUseCase`.
- `backend/app/interface/api/routes.py`: `GET /api/free-runs`; `POST /api/runs` passes `X-Device-Token` and `client_ip(request)` (the rate limiter's IP extraction).
- `backend/app/interface/api/error_handlers.py`: the 401 and 402 bodies.
- `backend/app/interface/api/app.py`: CORS allows `X-Device-Token`; lifespan runs `validate_configuration()`.
- Account scope: `domain/ports.py` `AccountFreeRunAllowance`; `domain/entities.py` `FreeRunScope`, `FreeRunPeriod`, `AccountFreeRunClaim`, `FreeRunStatus.scope`/`.period`; `domain/policies.py` `utc_day`, `start_of_next_utc_day`, `utc_month`, `start_of_next_utc_month`, `period_key`, `period_resets_at`; `infrastructure/persistence/account_free_runs.py` (`SqlAccountFreeRuns`, `InMemoryAccountFreeRuns`); `infrastructure/persistence/schema.py` + `backend/migrations/versions/0003_account_free_runs.py` and `0005_account_daily_free_runs.py`; `interface/api/dependencies.py` `get_optional_signed_in_principal` (used by `GET /api/free-runs`).

## API contract

`GET /api/free-runs` reads an optional `X-Device-Token`. If the token is missing or its signature does not verify, the endpoint issues a new one. It is read-only and never spends a run. It needs no `X-Client-ID` and is not rate limited, because issuing a token is free and stateless.

```json
{"device_token": "<id>.<sig>", "enabled": true, "scope": "device", "period": "day", "limit": 3, "used": 1, "remaining": 2, "resets_at": "2026-11-02T00:00:00Z"}
```

Every response carries `scope` (`"device"` or `"account"`, since 2026-11-13) and `period` (`"day"` or `"month"`, since 2026-11-14): how long the counter runs, so the client never has to infer it. `resets_at` is the end of that period (the next 00:00Z for `day`, 00:00Z on the 1st of next month for `month`).

| Caller | `scope` | `period` | `limit` | `resets_at` |
|---|---|---|---|---|
| Anonymous device (or signed in with the account allowance off / no account store) | `device` | `day` | `FREE_RUNS_PER_DEVICE` (3) | next UTC midnight |
| Signed in, free plan | `account` | `day` | `FREE_RUNS_PER_ACCOUNT_DAILY` (10) | next UTC midnight |
| Signed in, paid plan | `account` | `month` | `PAID_RUNS_PER_MONTH` (100) | 1st of next month, 00:00Z |

With a valid `Authorization: Bearer <JWT or vl_live_ key>` (or `X-Api-Key`), an account store, and `FREE_RUNS_PER_ACCOUNT_DAILY > 0`, the numbers are the account's for today; the device token is still issued or echoed exactly as for anonymous callers:

```json
{"device_token": "<id>.<sig>", "enabled": true, "scope": "account", "period": "day", "limit": 10, "used": 4, "remaining": 6, "resets_at": "2026-11-15T00:00:00Z", "plan": "free", "overage": false}
```

A bearer that does not verify is `401` with `WWW-Authenticate: Bearer`, the same as `/api/me` (and `503` when sign-in is not configured, also as `/api/me`); it is never silently downgraded to anonymous. An empty `Bearer ` with no key is anonymous. A signed-in caller with no account store (distributed, no `DATABASE_URL`) or with the account allowance off gets the `device` answer.

`enabled: false` means the allowance is off (`FREE_RUNS_PER_DEVICE <= 0`), so there is no limit and the client hides the banner. `limit`, `used` and `remaining` are then all 0. `used` is the device's own count only; the IP backstop is not reflected.

`POST /api/runs` applies the check only when no Gemini key is sent and the allowance is enabled:
- missing or invalid `X-Device-Token`: `401 {"detail": "...", "code": "device_token_invalid"}`. The client refetches a token and retries once.
- device or IP counter at its limit: `402 {"detail": "You have used your free runs. Add your own Gemini key to keep going.", "code": "free_runs_used", "scope": "device", "period": "day", "limit": <device limit>, "used": <device used>}`. The body is the same whichever counter tripped.
- account counter at its limit (signed-in free callers): `402 {"detail": "You have used today's free runs. Add your own Gemini key to keep going, or come back tomorrow.", "code": "free_runs_used", "scope": "account", "period": "day", "limit": 10, "used": 10}` (until 2026-11-14 it said "this month's" and had no `period`). A signed-in caller never gets `device_token_invalid`: no device token is needed or checked. A paid account never gets `free_runs_used` (it runs into extra runs instead, `billing.md`).

Other errors keep the plain `{"detail"}` shape.

## Rules

- **Order in `CreateRunUseCase`:** terms, then exactly one source, then `_admit` (free run), then `DAILY_RUN_CAP`, then save/probe/upload/enqueue. Invalid requests never spend a free run, and nobody without a free run reaches the daily budget or FFmpeg. Before this change the daily cap ran *before* the source check; it now runs after it.
- **Refunds at intake:** any exception after `_admit` hands the run back (`FreeRunAllowance.refund(claim)`). That covers the daily cap rejecting, `MediaValidationError` (for example over the duration cap) and scheduling failures. The claim records its UTC day, so a refund after midnight goes to the right day, and a counter never drops below 0.
- **Refunds when a link run is rejected before analysis** (owner decisions, 2026-11-02: "refund the free run on failed downloads", then "yes refund the duration cap one too"): a link run turned away before any Gemini call gets its free run back. Two triggers, both tracked by the `rejected_before_analysis` flag in `ProcessRunUseCase.execute`:
  - **The download fails:** `MediaProcessor.download_url` raises (any exception, normally the `MediaValidationError` the yt-dlp adapter wraps every failure in, such as "This post isn't public") **and** the caption fallback does not complete the run.
  - **The downloaded file fails the duration cap:** `MediaProcessor.enforce_duration_cap` raises on the link path (too long, or ffprobe cannot read the duration). This mirrors intake, which already refunds over-long uploads. The cap is never checked on the caption-fallback path, so a run that reached Gemini through captions can never trigger it.

  Everything else during processing is **not** refunded: a caption fallback that reached Gemini and failed there, normalize, Gemini upload/analysis, cancellation (job timeout), and every failure of an uploaded file. That includes the worker's duration re-check of an S3 upload: uploads are length-checked, and refunded, at intake. A caption rescue completes the run, so it keeps its free run.
- **Refunds when the stale-run check fails a run** (owner-approved, 2026-11-13): `GetRunUseCase` fails a `queued`/`processing` run that has gone quiet for longer than its job could take, and the person gets nothing, so the free run it holds (device or account) is handed back through `settle_free_run_holds` (`application/free_run_holds.py`). Only when the sweep's own write landed: if the worker completed the run first, nothing is refunded. If the worker later picks up the job, or was still running it, it stops and releases again; a `failed` run's release asks for a refund too (covering a sweep whose release failed), and every release acts only on the first call for a run, so the refund happens exactly once. A run whose record is gone is not refunded (its hold expires), and a run that failed in the worker's own pipeline already released its hold.
- **How the claim reaches processing:** after `_admit`, and before the job is enqueued, `CreateRunUseCase` calls `FreeRunAllowance.hold(run_id, claim)`. The store records the claim's resolved counter keys (day-scoped, IP already hashed), not the claim: Redis `videolens:free:held:{run_id}` (JSON list, 2-day TTL) in distributed mode, an in-process dict locally. Nothing new travels in job arguments (arq logs those) and nothing is added to `Run`, so nothing can leak through `api/schemas.py`. `ProcessRunUseCase` always calls `release(run_id, refund=rejected_before_analysis)` in its `finally`, which reads and deletes the hold in one `MULTI` (GET+DEL), then decrements those keys with the floor-at-0 refund script. Only the first release for a run finds the hold, so an arq retry or a second call can never refund twice. BYOK runs and runs with the allowance off never hold anything, so their release is a no-op. A failed intake drops the hold (`release(refund=False)`) before its own `refund(claim)`, for the same reason. Because the stored keys carry the claim's day, a refund after UTC midnight still goes to that day. A release that raises is logged and never changes the run's outcome; an unreleased hold just expires.
- **Atomicity (Redis):** one Lua script checks both counters and only then increments both (with a 2-day TTL), so a rejected request takes nothing and two racing requests cannot both take the last run. Keys: `videolens:free:device:{YYYY-MM-DD}:{device_id}` and `videolens:free:ip:{YYYY-MM-DD}:{sha256(ip)[:32]}`. The raw IP is never written.
- **No IP** (no forwarded header and no socket peer) means no IP backstop, rather than one shared bucket. The IP is the `X-Forwarded-For` entry the deployment's own proxy wrote for the client (`TRUSTED_PROXY_HOPS` from the right, 2 on Railway, see `cost-abuse-protection.md`), never the client-supplied first entry - a forged header used to reset this counter per request. Until 2026-11-07 the default of 1 picked Railway's per-request edge hop instead, so this backstop did not hold on Railway.
- **Token:** `<token_urlsafe(16)>.<base64url(HMAC-SHA256(secret, id))>`, checked with `hmac.compare_digest`. It is stateless, and any replica with the same secret verifies it.
- **Secret:** if `DEVICE_TOKEN_SECRET` is blank in local mode, a random key is generated per process and a warning is logged. If it is blank in distributed mode (`REDIS_URL` set) while the allowance is on, the API refuses to start, because replicas would reject each other's tokens. `docker-compose.yml` sets a local-only placeholder for this reason. Rotating the secret re-issues every device a token, so anonymous counts effectively reset.
- **MCP is unaffected:** BYOK is mandatory there, so every MCP call carries a key and skips this check entirely.
- **Seam for paid plans:** `_admit` is the single place that decides whether a caller may start a run on the shared key. The signed-in account allowance lives there (below); a paid plan check belongs there too.

## Signed-in free runs (account scope)

Owner decision 2026-11-13: a signed-in account gets free shared-key runs tied to the account so they follow the person across devices. This supersedes the auth plan's "free runs and sign-in do not interact" for this point. Owner decision 2026-11-14: `FREE_RUNS_PER_ACCOUNT_DAILY` (default 10) per **UTC day**, replacing 10 per calendar month (`FREE_RUNS_PER_ACCOUNT_MONTHLY`, no longer read).

- **Who:** `principal.authenticated` with an `account_id`: a Supabase session (`AuthMethod.TOKEN`) or an account API key (`API_KEY`, counted against the key's workspace owner, so ten keys are not ten allowances). Resolved by the existing `IdentifyCallerUseCase`; there is no second verifier.
- **Instead of, not on top of:** such a caller is admitted against the account counter only. No device token is required, the device counter is not touched, and the device answer is never consulted. Anonymous callers are exactly as before.
- **BYOK:** exempt, as for devices. **`DAILY_RUN_CAP` and the per-IP / per-account rate limits** still apply to everyone, unchanged, in the same order (account check, then daily cap).
- **No IP backstop for account runs** (decision, 2026-11-13): the account counter is the limit. The IP backstop exists because a fresh device id costs nothing (clear storage); a fresh account costs a Supabase sign-up, and the account has a stable id across devices and networks. Applying `FREE_RUNS_PER_IP` would also lock signed-in people behind shared networks out of runs they were granted. The account runs are not counted into the IP counter either.
- **Off switch:** `FREE_RUNS_PER_ACCOUNT_DAILY <= 0` turns the account allowance off; signed-in callers then fall back to the device rule (token, `FREE_RUNS_PER_DEVICE`, IP backstop). The two settings are independent: `FREE_RUNS_PER_DEVICE <= 0` removes the device limit but leaves signed-in callers on their daily account allowance. The old `FREE_RUNS_PER_ACCOUNT_MONTHLY` is ignored (settings ignore unknown variables), so a deployment that set it to 0 to switch the allowance off must set `FREE_RUNS_PER_ACCOUNT_DAILY=0` instead.
- **No account store** (distributed with blank `DATABASE_URL`): principals carry no `account_id`, so everyone is on the device rule.
- **Period:** the UTC day, keyed `"YYYY-MM-DD"` (`policies.utc_day`, through `period_key(FreeRunPeriod.DAY, now)`); `resets_at` is the next 00:00Z. The claim (`AccountFreeRunClaim`) records its key and the hold row stores it, so a refund after UTC midnight goes back to the day the run was taken from (mirrors the device claim's `day`).
- **Free and paid counters never collide:** both live in `account_free_runs`, but the free plan's key is a day (`"2026-11-14"`, 10 chars) and the paid plan's is a month (`"2026-11"`, 7 chars), so they are always different rows of the `(account_id, period)` key. Every run is counted on exactly one row, the one its claim names. Upgrading mid-day leaves today's free count on its daily row and starts the paid count on the monthly row (free runs used today do not reduce the 100); downgrading mid-month goes back to today's daily row (paid runs used today do not reduce the 10). Monthly rows written by free accounts before 2026-11-14 are simply no longer read by the free plan; in November 2026 only, the paid plan's monthly row of an account that used free runs under the old rule still holds those runs, so an upgrade that month starts below 100 (the old shared-counter behaviour, gone from December).
- **Changing the period:** the free period is `FreeRunPeriod.DAY`, passed explicitly in `CreateRunUseCase._admit`, `GetFreeRunsUseCase` and `GetBillingUseCase`; the paid one is `BillingPlans.PAID_RUNS_PERIOD`. `period` must stay at most 10 characters (varchar(10)).
- **Refunds:** identical to devices, through the same seams. `_admit` returns the claim together with the allowance it came from; intake failures after `_admit` (daily cap, duration cap, scheduling) drop the hold and refund; `ProcessRunUseCase._settle_free_run` releases on both allowances (a run holds at most one; the other is a no-op), so a link run `rejected_before_analysis` gets its account run back, at most once.
- **Atomicity:** one statement, `INSERT ... ON CONFLICT (account_id, period) DO UPDATE SET used = used + 1 WHERE used < :limit RETURNING used`; no row back is a refusal. `period` here is the day or month key. On Postgres the conflict path takes the row lock, so racing requests serialise on it and cannot exceed the limit. Refund is `UPDATE ... SET used = used - 1 WHERE used > 0`. Release reads the hold, deletes it, and only the request whose `DELETE` removed the row (rowcount 1) refunds.
- **Storage:** with the identity tables (Postgres via `DATABASE_URL`), not Redis: the count belongs to the account, the paid counter must last a month, and both go with the account. Tables (migration `0003_account_free_runs`, `period` widened by `0005_account_daily_free_runs`): `account_free_runs` (`account_id` FK → `accounts.id` ON DELETE CASCADE, `period` varchar(10), `used` int, PK `(account_id, period)`) and `account_free_run_holds` (`run_id` PK, `account_id` FK cascade, `period` varchar(10), `created_at`; rows older than 2 days are pruned on the next hold, like the Redis holds' TTL). RLS on, backend-role policy and grants, as for the identity tables. Without `DATABASE_URL` in local mode the in-memory store (`InMemoryAccountFreeRuns`) is used, alongside the in-memory account store; distributed mode has no account ids without a database, so no Redis counterpart was needed.
- **Account deletion** (`DELETE /api/me`): `SqlAccountDeleter` deletes both tables' rows for the account in its transaction (the cascade covers Postgres anyway; SQLite does not enforce foreign keys); the in-memory deleter drops them too.
- **Deploy order:** apply `0003_account_free_runs` before deploying this code. Applied on `videolens-dev` 2026-11-13 (rendered offline, run via the Supabase connector; `alembic_version` = `0003_account_free_runs`, RLS on both tables, policy and grants for `videolens_api` only). Not yet applied to production. Without the tables every signed-in run without a key fails at admission (a 500), and `GET /api/free-runs` with a bearer fails too.
- **`0005_account_daily_free_runs`** (2026-11-14, not applied anywhere yet): `ALTER TABLE account_free_runs ALTER COLUMN period TYPE VARCHAR(10)` and the same on `account_free_run_holds`. Widening a varchar is catalog-only on Postgres (no rewrite, no index rebuild, a brief lock); RLS, the `videolens_api_all` policies (`USING (true)`, no column named) and the grants belong to the table and are untouched. It sits after `0004_billing`, so a database at 0003 (dev) needs 0004 too (`alembic upgrade 0003_account_free_runs:0005_account_daily_free_runs --sql`; 0004 is harmless with billing off). Apply it **before** deploying the daily code: on Postgres a 10-char key does not fit varchar(7), so every signed-in free run would fail at admission. Downgrade deletes the daily rows and holds first, then narrows back to varchar(7).
- **Bypass:** a new account is a fresh 10. That costs a Supabase sign-up per 10 runs; on `videolens-dev` sign-up requires a confirmed email ("Confirm email" on, anonymous sign-ins off, read in the dashboard 2026-11-13), so each fresh 10 costs a working inbox. Check the same on the production project before launch. `DAILY_RUN_CAP` still bounds total spend.

## The paid plan (docs/backend/billing.md)

With billing configured, a paid account (active or trialing subscription)
uses the same `account_free_runs` table on its own **monthly** row
(`"YYYY-MM"`, `BillingPlans.PAID_RUNS_PERIOD`), with the limit
`PAID_RUNS_PER_MONTH` (100). Since 2026-11-14 that is a different row from
the free plan's daily ones, so free runs used today do not count toward the
100 (until then free and paid shared one monthly row). Past it, a run is admitted as an extra run (billed once it
completes) instead of a 402; the only refusal is the monthly safety cap,
`402 {"code": "extra_runs_cap", "limit"}`. Paid runs skip `DAILY_RUN_CAP`.
`past_due`, `unpaid` and `canceled` are on the free rules above.

`GET /api/free-runs` for a signed-in caller gains `"plan": "free" | "paid"`
and `"overage": bool` (true on the paid plan); on the paid plan `limit`,
`used` and `remaining` are the plan's and `period` is `"month"`. Anonymous
responses leave `plan` and `overage` out. `AccountFreeRunAllowance.status`
and `try_consume` take optional `limit=` and `period=` (default the free
daily one) for this; with an explicit limit the store answers whenever it
exists, even with `FREE_RUNS_PER_ACCOUNT_DAILY <= 0`.

## How easy is it to bypass

- **Clearing storage or a private window** gives a new device token and a fresh device count. This is bounded by the per-IP counter (10/day by default). `GET /api/free-runs` (which issues the token) is also rate-limited per IP since 2026-11-07 (`READ_RATE_LIMIT_PER_MINUTE`).
- **New IP** (VPN, toggling mobile data, another network) gives a fresh IP counter. Combined with clearing storage, that resets both counters. Nothing here stops a determined user with many IPs.
- **Forged or edited tokens** are rejected by the HMAC check. A client cannot invent device ids.
- **The global `DAILY_RUN_CAP`** still bounds total spend regardless of devices or IPs, and the per-IP `RATE_LIMIT_PER_HOUR` still applies.
- **False positives:** on shared networks (offices, campuses, carrier NAT) many people share one IP and can hit `FREE_RUNS_PER_IP` together. They see the same 402 and can add their own key.

The purpose is to stop casual overuse of the shared key, not to authenticate anyone.

**Tests (account scope)**: `backend/tests/application/test_create_run.py::AccountFreeRunAdmissionTests` (admitted and counted without a device token, device counter untouched, 11th refused with scope account, period day, the "today" message and the account numbers, API key spends the owner's runs, BYOK exempt, anonymous unchanged, device 402 scope and period, disabled and unwired fall back to the device rule, signed in without an account store, intake refunds, day rollover), `test_process_run.py::AccountFreeRunRefundTests` (download failure and duration cap refund, refund after UTC midnight goes to the claim's day, Gemini failure does not, no double refund), `test_get_free_runs.py` (period and next-midnight `resets_at`), `test_billing.py` (paid counter monthly, upgrade mid-day and downgrade mid-month never double count, `runs_period`), `backend/tests/infrastructure/persistence/test_account_free_runs.py` (day/month keys and resets; SQL on SQLite and in-memory: limit, read-only status, UTC-midnight rollover, refund after midnight to the claim's day, paid monthly counter separate from the daily one, floor at 0, release once, concurrent takes never exceed the limit (SQL on a file database with a connection per request), off at <= 0, stale hold pruning, deletion clears usage and holds; 0003 upgrade/downgrade on SQLite, Postgres branch mocked; 0005 widen, keys/cascade/indexes kept, downgrade keeps only monthly rows), `backend/tests/interface/api/test_free_run_routes.py::AccountFreeRunRouteTests` (account response shape with `period`, next-midnight `resets_at`, token echoed, invalid bearer 401 like `/api/me`, unknown key 401, 503 unconfigured, empty bearer anonymous, disabled falls back, account 402 body, CORS `Authorization`).

**Tests**: `backend/tests/infrastructure/quota/test_device_tokens.py` (sign/verify/tamper, startup check), `backend/tests/infrastructure/quota/test_free_run_allowance.py` (per device, per IP, day keys, refund, read-only status; hold/release: refund on release, at most once, release without refund, nothing held, after-midnight day, no raw IP in the hold), `backend/tests/application/test_create_run.py` (`FreeRunAdmissionTests`, including the hold being placed, BYOK holding nothing, a rejected intake dropping the hold and refunding once), `backend/tests/application/test_process_run.py` (`FreeRunDownloadRefundTests`: download failure refunds, unexpected download error refunds, analyze failure does not, BYOK does not, no double refund on a retried job, caption rescue keeps it, captions failing at Gemini do not, duration cap after download refunds (once, and not for BYOK), an S3 upload over the cap in the worker does not, normalize after download does not, uploads do not, a failing release leaves the run outcome alone), `backend/tests/interface/api/test_free_run_routes.py` (GET endpoint, 401/402 bodies, CORS). The Redis Lua and `MULTI` paths have no automated test (there is no Redis in CI).

## Changelog
- 2026-11-01 · backend agent (Phase 5b) · created: per-device free-run allowance, `GET /api/free-runs`, 401/402 codes on `POST /api/runs`
- 2026-11-02 · backend agent (free-run download refund) · a link run whose download fails now gets its free run back: `FreeRunAllowance.hold`/`release`, held at intake, released in `ProcessRunUseCase`; other processing failures stay unrefunded
- 2026-11-02 · backend agent (duration-cap refund) · a link run that downloads but fails the duration cap now also gets its free run back; flag renamed `download_failed` → `rejected_before_analysis`; normalize, Gemini and upload failures stay unrefunded
- 2026-11-07 · security-check · IP backstop keyed on the proxy-appended X-Forwarded-For entry, not the client-supplied one; `GET /api/free-runs` rate-limited
- 2026-11-07 · general-purpose subagent (dispatched by videolens-9f) · IP backstop now holds on Railway: `TRUSTED_PROXY_HOPS` default 2 (Railway's edge writes `<client>, <edge hop>`)
- 2026-11-13 · backend agent · signed-in free runs: `FREE_RUNS_PER_ACCOUNT_MONTHLY` (10/UTC month per account) instead of the device counter, no IP backstop, `scope` on every `GET /api/free-runs` response and 402, account responses with a bearer, `0003_account_free_runs`, refunds through the same seams
- 2026-11-13 · main session · `0003_account_free_runs` applied on `videolens-dev` and verified; production still pending
- 2026-11-13 · main session · confirmed in the Supabase dashboard that `videolens-dev` requires email confirmation for sign-up and has anonymous sign-ins off
- 2026-11-13 · backend agent · a run the stale-run check fails gets its free run back, exactly once across the sweep, the worker and arq retries; recordless runs are still not refunded
- 2026-11-13 · backend agent · paid plan: the account counter doubles as the paid plan's included runs (`limit=`), `plan`/`overage` on `GET /api/free-runs` for signed-in callers, `extra_runs_cap` 402
- 2026-11-14 · backend agent · signed-in free accounts: 10 per UTC day (`FREE_RUNS_PER_ACCOUNT_DAILY`, replaces `FREE_RUNS_PER_ACCOUNT_MONTHLY`), day keys "YYYY-MM-DD" beside the paid plan's monthly "YYYY-MM" (separate rows, no double counting), `period` on every `GET /api/free-runs` response and 402, account 402 says "today", migration `0005_account_daily_free_runs` (period varchar(10)), refunds pinned to the claim's day
