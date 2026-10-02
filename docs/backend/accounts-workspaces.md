# Accounts, workspaces & entitlements

Turns a verified credential into a `Principal` with a workspace and a plan, and decides what that plan allows. Everything is config-gated on `DATABASE_URL`: with no database the app behaves exactly as it did before plans existed (anonymous or signed-in, deployment-wide limits, Redis-only history).

**Files**
- `backend/app/domain/entitlements.py` — the pricing table as data: `Plan`, `Entitlement`, `entitlement_for(plan)`, `billable_minutes`, `media_resolution_for`, `estimate_cost_usd`, `can_start_run`. The only place plan numbers live.
- `backend/app/domain/entities.py` — `Principal` (now carries `method`, `account_id`, `workspace_id`, `plan`, `email`; `owner_id` is `workspace:{id}` when a workspace is present, else the subject), `Account`, `Workspace`, `WorkspaceMember`, `UsageEvent`, `UsageSummary`, `AuthMethod`, `WorkspaceRole`.
- `backend/app/domain/ports.py` — `AccountDirectory`, `UsageMeter`, `ApiKeyRepository`, `RunArchive`, `BillingGateway` Protocols; each has an `enabled` property the use cases read.
- `backend/app/application/identify_caller.py` — `IdentifyCallerUseCase`: `from_token_claims` (JWT `sub`/`email` → account + default workspace, created on first sight), `from_api_key`, `from_client_id`.
- `backend/app/application/entitlements.py` — `EntitlementResolver`: workspace lookup, `for_workspace` (plan table + per-workspace `max_duration_seconds` override, FREE clamped to the deployment's `MAX_DURATION_SECONDS`), `minutes_used`, `usage_summary`.
- `backend/app/application/get_account.py` — `GetAccountUseCase` behind `GET /api/me`.
- `backend/app/application/record_usage.py` — `RecordUsageUseCase`: one `UsageEvent` per metered run (minutes rounded up to 0.01, token counts, cost estimate), reported to the billing meter first, then persisted locally. A meter failure never loses the local row.
- `backend/app/infrastructure/persistence/{database,schema,account_directory,usage_meter}.py` — one async SQLAlchemy engine (`Database`; asyncpg for Postgres, aiosqlite for tests), Core tables `accounts`, `workspaces`, `workspace_members`, `usage_events` (plus `runs`, `run_results`, `api_keys` documented in their own docs), and the two adapters.
- `backend/migrations/` + `backend/alembic.ini` — Alembic, run programmatically by `Container.prepare_database()` at API and worker startup when `DB_AUTO_MIGRATE=true` (default). `alembic upgrade head` from `backend/` works too with `DATABASE_URL` in the environment.
- `backend/app/interface/api/dependencies.py` — `get_principal` order: API key (`X-Api-Key` or `Authorization: Bearer vl_live_…`) → JWT bearer → `X-Client-ID`. `get_signed_in_principal` refuses anonymous callers with 401.
- `backend/app/interface/api/routes.py` — `GET /api/me`.

**Plans** (`_PLAN_TABLE`): free 30 min/month, 3 min per video (deployment default), 200 MB · pro 600 min, 30 min per video, 1 GB, $0.05/min overage, library · studio 3000 min, 60 min, 2 GB, 3 seats, API access · scale 12000 min, 120 min, 2 GB, 10 seats, $0.04/min. A plan with `overage_usd_per_minute=None` is a hard cap (402 `plan_limit` once the minutes are gone); a plan with a price keeps running and bills the extra.

**Where the plan is enforced**: `CreateRunUseCase` resolves the entitlement once at intake, refuses over-allowance runs with `PlanLimitError` (402), passes `max_file_size_mb` to the upload saver and `max_duration_seconds` to the duration probe (`DurationLimitError`, 400 with `code: duration_limit`, `duration_seconds`, `limit_seconds`), and stores `workspace_id`, `plan`, and `max_duration_seconds` on the `Run` so the worker needs no plan lookup. Paid plans skip the shared `DAILY_RUN_CAP` (their minutes are invoiced); a caller-supplied Gemini key skips both the allowance and the cap.

**Metering**: `ProcessRunUseCase` records usage only after the result is stored, only for runs with a `workspace_id`, and never for BYOK runs. Media over 15 minutes is analyzed at `MEDIA_RESOLUTION_LOW` (a third of the tokens); the resolution is carried onto the usage event's cost estimate.

**Ownership**: with a workspace, `owner_id` is `workspace:{id}`, so every member sees the same history and library. API-key callers are `key:{key_id}` subjects bound to the key's workspace. Anonymous callers stay `client:{id}` and never touch the database.

**Config**: `DATABASE_URL` (Postgres; `postgres://` and `postgresql://` are normalized to the asyncpg driver; SQLite accepted for single-machine use), `DB_AUTO_MIGRATE`. `GET /api/capabilities` reports a `database` row: `disabled` without a URL, `unavailable` when the ping fails.

**Tests**: `tests/domain/test_entitlements.py`, `tests/application/{test_identify_caller,test_record_usage,test_create_run_plans,test_process_run_metering}.py` (fakes in `tests/application/fakes.py`), `tests/infrastructure/persistence/test_sql_adapters.py` (SQLite through the real adapters and migration), `tests/interface/api/test_account_routes.py`.

## Changelog
- 2026-09-17 · main session · created with the accounts/workspaces/entitlements implementation (Phase 0 + 1 of `docs/product-plan-100k.md`)
