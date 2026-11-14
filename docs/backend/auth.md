# Authentication, accounts and API keys

Every request resolves to one `Principal`: an anonymous browser, a signed-in
person (a Supabase access token), or an agent holding an API key. Phase 1 of
`docs/auth-plan.md` (backend identity) is implemented on `feat/auth-supabase`,
phase 2 (frontend sign-in) on the same branch, and phase 3's backend half
(account deletion, `DELETE /api/me`, and the `database` capability) is
reviewed and committed on the same branch (2026-11-09). None of it is merged yet.

## Files

| Layer | File | What |
|---|---|---|
| domain | `entities.py` | `AuthMethod`, `Principal` (+ `method`, `account_id`, `workspace_id`, `email`, `owner_id`), `Account`, `Workspace`, `WorkspaceRole`, `ApiKey`, `ApiKeyCreated` |
| domain | `entitlements.py` | `Plan.FREE` only, `Entitlement`, `entitlement_for` |
| domain | `policies.py` | `is_valid_client_id`, `looks_like_api_key` (`vl_live_`), `can_access_run`, `quota_key`, `quota_key_from_headers` (fallback) |
| domain | `errors.py` | `AuthenticationError` 401, `ForbiddenError` 403, `ApiKeyNotFoundError` 404, `ApiKeyLimitError` 409, `ClientIdInvalidError` 400, `AccountDeletionError` 500, `AuthNotConfiguredError` / `AccountsNotConfiguredError` 503 |
| domain | `ports.py` | `TokenVerifier`, `AccountDirectory`, `ApiKeyRepository`, `AccountDeleter`, `RunRepository.delete_for_owner` |
| application | `identify_caller.py` | `IdentifyCallerUseCase`: the whole credential precedence |
| application | `entitlements.py`, `get_account.py` | `EntitlementResolver.for_principal`, `GetAccountUseCase` (`/api/me`) |
| application | `api_key_access.py`, `create_api_key.py`, `list_api_keys.py`, `revoke_api_key.py` | key management and its gate |
| application | `delete_account.py` | `DeleteAccountUseCase` (`DELETE /api/me`) |
| infrastructure | `auth/jwt_verifier.py` | `JwtVerifier` (PyJWT, one caching `PyJWKClient`) |
| infrastructure | `persistence/database.py`, `schema.py` | async engine (asyncpg / aiosqlite), the four tables |
| infrastructure | `persistence/account_directory.py`, `api_key_repository.py` | SQL and in-memory adapters |
| infrastructure | `persistence/account_deleter.py` | `SqlAccountDeleter`, `InMemoryAccountDeleter` |
| infrastructure | `persistence/identity_users.py` | `SqlIdentityProviderUsers` (`auth_user_exists`), `AlwaysPresentIdentityProviderUsers` |
| infrastructure | `persistence/run_repository.py` | `RunStore.delete_for_owner` (Redis owner index, or memory) |
| infrastructure | `health/probes.py` | `AuthProbe` (`auth` capability), `DatabaseProbe` (`database` capability) |
| interface | `api/dependencies.py` | `get_principal`, `get_signed_in_principal`, `require_person` |
| interface | `api/routes.py`, `schemas.py` | `GET /api/me`, `DELETE /api/me`, `GET|POST /api/keys`, `DELETE /api/keys/{id}` |
| migrations | `backend/alembic.ini`, `backend/migrations/` | `0001_identity`, `0002_auth_user_deleter` |

## Who is calling (`IdentifyCallerUseCase.resolve`)

The order is fixed:

1. **API key.** This means `X-Api-Key: vl_live_...`, or `Authorization: Bearer vl_live_...`. The prefix routes it, so an agent can use either header. `X-Api-Key` wins over a bearer token. The key is looked up by SHA-256. A key that is unknown or revoked, or whose workspace no longer exists, gets a 401. The result is `Principal(subject="key:<id>", method=API_KEY, workspace_id=<key's workspace>, account_id=<workspace owner>)`.
2. **Bearer token.** Anything else after `Bearer ` is verified by `JwtVerifier`. On success the `sub` resolves an account: the first sign-in creates the account, a "Personal" workspace and an owner membership, and later sign-ins keep the email current. The result is `Principal(subject="user:<sub>", method=TOKEN, account_id, workspace_id, email)`. Any verification failure becomes a generic `401 "Invalid access token."`, and only the exception class is logged. An unconfigured verifier is the exception: it gives `503` (`AuthNotConfiguredError`, now a domain error so the interface no longer imports the adapter). A blank `Bearer ` header counts as no credential.
3. **Anonymous.** This needs `ALLOW_ANONYMOUS` (default true) and a valid `X-Client-ID`. It resolves to `Principal(subject="client:<id>", method=ANONYMOUS)`. A missing or malformed id gets a 400. The client id is self-reported, so it scopes which runs a browser sees. It is never a quota identity.

`get_principal` leaves the principal on `request.state.principal` for the rate limiter (see below).

### JWT rules (`JwtVerifier`)

- Only RS256 and ES256 are accepted (Supabase signs with ES256). HS256 is refused.
- `exp`, `iat` and `sub` are required. There is `leeway=30` seconds of clock skew.
- `iss` must equal `AUTH_ISSUER`. `aud` is checked when `AUTH_AUDIENCE` is set (Supabase: `authenticated`) and skipped when it is blank.
- `configured` means `AUTH_JWKS_URL` and `AUTH_ISSUER` are both set. Before phase 1 the audience was also required.
- A single `PyJWKClient(cache_keys=True, lifespan=600, timeout=5)` lives for the whole process.
- **The header is screened before any key lookup.** A disallowed `alg` or a missing/non-string `kid` is refused without touching the network. Malformed tokens are refused the same way.
- **JWKS refetches on an unknown `kid` are throttled.** The cached set is consulted first. A miss forces at most one refetch per 60 seconds per process (that is how a rotated key is picked up); between refreshes an unknown `kid` is simply a 401. This was a review finding: PyJWT's `get_signing_key_from_jwt` refetches on every miss, and since a request that 401s in `get_principal` never reaches the rate limiter, a loop of forged tokens could make the API hammer Supabase's JWKS endpoint.
- **The `role` claim must be `authenticated`, and `is_anonymous: true` is refused** (in `IdentifyCallerUseCase.from_token_claims`, 401 "Invalid access token."). If Supabase anonymous sign-ins were ever enabled, each throwaway sign-in would otherwise get an account, API keys and its own rate bucket. A non-Supabase IdP would need to emit the same claim.
- The `Bearer` scheme is matched case-insensitively (RFC 9110), here and in the limiter's header fallback (`policies.bearer_credential`).
- A rejection logs the reason and the `kid`, never the token.

Supabase values: `AUTH_JWKS_URL=https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`, `AUTH_ISSUER=https://<ref>.supabase.co/auth/v1` and `AUTH_AUDIENCE=authenticated` (see `backend/.env.example`).

### Run ownership in this phase

`Principal.owner_id` is the `subject`. `create_run.py` was frozen for phase 1 and stamps `principal.subject` on a run, so `can_access_run` and `list_runs` compare against the same value. A signed-in person's runs therefore belong to `user:<sub>`, and API-key runs to `key:<id>`. Workspace-scoped ownership is a later change: it means switching `owner_id` to `workspace_id` for TOKEN and API_KEY callers, plus one line in `create_run.py`.

## Dependencies on routes

- `get_principal`: any caller, used by the existing run routes and unchanged for them.
- `get_signed_in_principal`: a person or an API key. Anonymous gets 401. Used by `GET /api/me`.
- `require_person`: a signed-in person only. Anonymous gets 401 and an API key gets 403, so a leaked agent key cannot mint more keys. Used by all `/api/keys` routes and by `DELETE /api/me`.

A 401 carries `WWW-Authenticate: Bearer`.

## Endpoints

| Route | Who | Returns |
|---|---|---|
| `GET /api/me` | person or key | `subject`, `method`, `email`, `account_id`, `workspace {workspace_id, name}`, `entitlement {plan, max_duration_seconds, max_file_size_mb, metered, api_access, library}`, `accounts_enabled`, `saved_history {saving, expires_at}` (`saved-history.md`) |
| `GET /api/keys` | person (workspace owner) | `{keys: [...]}`, newest first, including revoked keys (`active: false`, `revoked_at`) |
| `POST /api/keys` `{name}` | person (workspace owner) | 201 with the key and its `secret`, shown once. Names are trimmed to 80 characters and default to "Unnamed key" |
| `DELETE /api/keys/{key_id}` | person (workspace owner) | 204. A key from another workspace or an unknown key gets 404 |
| `DELETE /api/me` | person only | 200 `{"status": "pending_deletion", "purge_at"}` (was 204 before 2026-11-14). Anonymous 401, API key 403, no account store 503, a failure 500 (see *Account deletion*) |
| `POST /api/me/restore` | person only, even while held | `{"restored": bool}`; 410 `restore_window_closed` after `purge_at` |

**A held account** (deleted, inside its 30-day hold) gets
`410 {"detail", "code": "account_pending_deletion", "purge_at"}` from every
route that resolves a bearer token, except `POST /api/me/restore`
(`require_person_even_if_deleted`); its API keys get `401 Invalid API key.`
(`IdentifyCallerUseCase`, `docs/backend/saved-history.md`).

The entitlement is the single free plan at the deployment's limits (`MAX_VIDEO_DURATION_SECONDS`, `MAX_FILE_SIZE_MB`), with `metered=false`, `api_access=true` and `library=false`. There is no plan gate on API keys.

CORS lists `Authorization`, `Content-Type`, `X-Api-Key`, `X-Client-ID`, `X-Gemini-Api-Key` and `X-Device-Token`, and allows `DELETE`.

## Account deletion (`DELETE /api/me`, phase 3)

**Since 2026-11-14 this is a 30-day hold, then the removal below**
(`docs/backend/saved-history.md`, owner decision). `DeleteAccountUseCase`
now cancels the subscription (step 0), deletes the Redis runs (step 1) and
sets `accounts.deleted_at` / `purge_at`; the Supabase user and every row
stay, hidden, so the person can sign in and `POST /api/me/restore`. After
`purge_at` the worker's hourly `account_cleanup` cron does the removal:
the Supabase user first (step 3, the same `SECURITY DEFINER` function),
then the rows (step 2, re-checked `purge_at <= now` under a row lock, and
now including `saved_runs`). So the order below is reversed at purge time:
identity first, so nobody can sign in to a half-removed account; a failure
leaves the account row and the next tick retries. The rest of this section
describes the steps themselves, which are unchanged.

The steps, as originally designed for an immediate removal:

1. **Server-side runs.** `RunRepository.delete_for_owner` for `user:<sub>` and for `key:<id>` of every key in the person's workspace (runs an agent created belong to the same person). In Redis the owner index (`videolens:owner:<owner>:runs`, at most 50 ids) is the only way to find them; the run keys and the index go. Best effort: a run-store failure is logged and the deletion carries on, because runs expire within `RUN_TTL_SECONDS` anyway. A run a worker is still processing stays gone (`_update` reads before it writes and skips a missing run).
2. **Identity rows, one transaction.** `AccountDeleter.delete_account`: `api_keys` of the workspaces the account owns, then `workspace_members` (of those workspaces, and the account's own memberships elsewhere), then `workspaces`, then `accounts`. Children first, since the foreign keys have no `ON DELETE CASCADE`. A failure rolls the whole transaction back and is a 500; the Supabase user is untouched.
3. **The Supabase user, last.** `AccountDeleter.delete_identity` runs `SELECT videolens_private.delete_auth_user(:uuid)`. It goes last so that if anything earlier fails, the person still exists in `auth.users`, their session still verifies, and a retry can finish. A failure here is also a 500 (rows already gone).

**Retry-safe, and final once complete.** The access token is stateless and still verifies for up to an hour after deletion. Left alone, it would re-create an empty account on its next request (`resolve_account` inserts on first sight of a subject) and could then mint an API key bound to a subject nobody can sign in as again, so nobody could ever list or revoke it (review finding, 2026-11-09; reachable with no attacker, e.g. a second device still signed in). So before creating rows for a subject it has not seen, the account directory asks `IdentityProviderUsers.exists` (on Postgres, `videolens_private.auth_user_exists(uuid)`); a gone user is `401 "Invalid access token."` with nothing written. `CreateApiKeyUseCase` asks again right before issuing a key, which closes the race where a concurrent request re-creates rows between step 2 and step 3. Consequences:

- A retry after a step 2 or step 3 failure still works and returns 204: the Supabase user still exists, so the person resolves and the steps run again (step 2 finding no rows is not an error; step 3 always runs).
- **A second `DELETE /api/me` after a complete deletion is 401, not 204**, and so is every other signed-in request with that token (`/api/me`, `/api/keys`). The frontend signs out after a 204 anyway.
- Reads of an existing account never ask (no extra query per request). An account whose rows still exist resolves normally even if the user is gone, so a retry can always find the person.
- On SQLite and the in-memory store there is no provider to ask: every subject exists.

Only the account id is logged (no email, no subject).

**Where the identity step is skipped.** On SQLite (no `auth` schema) and with the in-memory store (local `uvicorn` without `DATABASE_URL`) `delete_identity` logs and returns False; a real Supabase user, if any, stays. A subject that is not a UUID (a non-Supabase IdP) is skipped the same way, with a WARNING.

**503** when there is no account store (blank `DATABASE_URL` in distributed mode), the same condition `/api/keys` uses. The use case also refuses an API-key principal itself (403), behind `require_person`.

The frontend keeps the person's own local data (IndexedDB History, the BYOK key) and only signs out; see `docs/frontend/auth-sign-in.md`.

### Step 0: the Stripe subscription (paid plan)

Before anything else (runs, rows, identity), `DeleteAccountUseCase` cancels
the account's Stripe subscription immediately, with no proration refund
(`invoice_now=true, prorate=false`), after reporting any completed extra
runs still due. If Stripe fails, or billing was switched off while a live
subscription is on file, the request is refused with
`503 {"detail": "We couldn't cancel your subscription, so your account was not deleted. Please try again.", "code": "subscription_cancel_failed"}`
and nothing is deleted. The `billing_accounts` and `billing_extra_runs`
rows then go with the account (explicit delete plus `ON DELETE CASCADE`).
The Stripe Customer record stays in Stripe (invoices). `docs/backend/billing.md`.

### Why a `SECURITY DEFINER` function (`0002_auth_user_deleter`)

Supabase's `postgres` holds `DELETE` on `auth.users` with `is_grantable = NO` (verified on `videolens-dev`, 2026-11-08), so 0001's direct grant to `videolens_api` never takes. The alternative, the Admin API with a service-role key on Railway, is what auth-plan decision 2 rules out. So `0002` creates, on Postgres only:

```sql
CREATE SCHEMA IF NOT EXISTS videolens_private;
REVOKE ALL ON SCHEMA videolens_private FROM PUBLIC;
GRANT USAGE ON SCHEMA videolens_private TO videolens_api;
CREATE OR REPLACE FUNCTION videolens_private.delete_auth_user(target uuid)
  RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = ''
  AS $$ DELETE FROM auth.users WHERE id = target $$;
CREATE OR REPLACE FUNCTION videolens_private.auth_user_exists(target uuid)
  RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
  AS $$ SELECT EXISTS (SELECT 1 FROM auth.users WHERE id = target) $$;
-- for each of the two functions:
REVOKE ALL ON FUNCTION videolens_private.delete_auth_user(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION videolens_private.delete_auth_user(uuid) TO videolens_api;
```

`auth_user_exists` is the read-only partner the first-sight check uses (above); the backend role cannot read `auth.users` either.

- The functions are owned by whoever runs Alembic, which must be `postgres`: it runs with the owner's rights, so it can delete the row the backend role cannot.
- `videolens_private` is never added to PostgREST's exposed schemas, so the function is not reachable over the REST API.
- `SET search_path = ''` is Supabase's hardening rule for definer functions: the body names `auth.users` fully, and nothing on a caller's search path can shadow it.
- `PUBLIC` loses the default `EXECUTE` and `USAGE`; only the backend role gets them.
- Online, the migration fails (Alembic records nothing) if the role is missing, if `has_function_privilege('videolens_api', …, 'EXECUTE')` is false afterwards for either `videolens_private.delete_auth_user(uuid)` or `videolens_private.auth_user_exists(uuid)`, or if `anon`/`authenticated` have `USAGE` on the schema. Offline (`--sql`) these checks are skipped, so after applying a rendered script run the same `has_function_privilege` query by hand.
- Downgrade drops both functions, then the schema (`RESTRICT`: anything else that lands there stops the downgrade rather than vanishing). SQLite is a no-op both ways.

### Data after account deletion

Researched 2026-11-09 against `videolens-dev` (ref `pjekwwiaocywdbwqgtgl`, org `gagan-dev`, Pro, Postgres 17.11) and the Railway workspace "gaganbirru's Projects". Read-only throughout: catalog `SELECT`s, Logs counts (no values read), dashboard pages viewed without changing anything. Migration 0002 was not applied at research time; it was applied later the same day (see the changelog), and every Supabase row below assumes it.

| Location | What remains after `DELETE /api/me` | How long | Status and evidence |
|---|---|---|---|
| Our tables (`accounts`, `workspaces`, `workspace_members`, `api_keys`, and since 2026-11-13 `account_free_runs`, `account_free_run_holds`) | Nothing in the live database | Gone at once (one transaction). **Since 2026-11-14:** kept, hidden, for the 30-day hold, then removed by the hourly cleanup together with `saved_runs` (`saved-history.md`); the Supabase user rows below likewise go at purge, not at `DELETE /api/me` | **Verified** in code: `account_deleter.py` `delete_account` (free-run rows deleted explicitly and by `ON DELETE CASCADE`) |
| `auth.users` + `identities`, `sessions` (and through it `refresh_tokens`, `mfa_amr_claims`), `mfa_factors`, `one_time_tokens`, `oauth_authorizations`, `oauth_consents`, `webauthn_*`, `mfa_recovery_code_sets` | Nothing: each references `auth.users` (directly or via `sessions`/`mfa_factors`) with `ON DELETE CASCADE` | Gone at once | **Verified**: `pg_constraint` query on the project. Only `auth.scim_users` is `SET NULL` (SSO/SCIM, unused here) |
| `auth.flow_state` | One row per email sign-up/sign-in flow: `user_id` (UUID), provider type, timestamps. No email column. No FK to `auth.users`, so not cascaded | Until Supabase Auth's cleanup removes rows older than 24 h | **Verified**: column list and absent FK (catalog); cleanup rule in `supabase/auth` `internal/models/cleanup.go`: "created_at < now() - interval '24 hours'". That the hosted cleanup actually runs on this project is **unverified** (the only row is under 24 h old) |
| `auth.audit_log_entries` (table) | Nothing is written: 0 rows although a sign-up happened | n/a | **Verified**: `count(*) = 0`; dashboard Authentication → Audit Logs shows "Write audit logs to the database" switched off. If switched on: no FK to `auth.users`, `payload` would hold `actor_id` and `actor_username` (the email), and no cleanup rule touches it, so rows would stay until deleted by hand |
| Supabase Auth audit logs (Logs, source `auth_audit_logs`) | Events with `actor_id` and `actor_username` = the email (sign-up, confirmation, token refresh/revoke) | Pro: 7 days viewable | **Verified** content: count query, 4 of 4 events carry an email in `actor_username`. Retention: supabase.com/pricing, Pro "Auth audit logs" 7 days. Physical purge after 7 days **unverified** |
| Supabase Auth server logs (`auth_logs`) | Some lines carry the email (4 of 37 in 24 h), plus `actor_id` and client IP (`remote_addr`) | Pro: 7 days viewable | **Verified** content (count query); retention supabase.com/pricing, "7-day log retention". Purge **unverified** |
| Supabase API gateway (`edge_logs`) | Client IP, path, user agent per request; no email in the 40 sampled lines | Pro: 7 days viewable | **Verified** for one 24 h window only; retention as above |
| Supabase Postgres logs (`postgres_logs`) | No email in the sampled window | Pro: 7 days viewable | **Verified** for one 24 h window only |
| Supabase daily backups | The whole database as at backup time, including `auth.users` (email) and our rows. A restore brings the deleted person back | Pro: last 7 days of daily backups, so at most about 7 days after deletion | **Verified**: dashboard Database → Backups lists daily **PHYSICAL** backups (07 and 08 Nov 2026); docs.supabase.com/guides/platform/backups: "Pro Plan projects can access the last 7 days of daily backups". Whether older backups are destroyed rather than hidden **unverified** |
| Supabase Point-in-Time Recovery | Not enabled | n/a | **Verified**: dashboard Backups → Point in time shows "available as an add-on" |
| Supabase as processor | Customer data falls under the DPA, not the privacy notice | DPA cl. 11.2: delete all copies after the agreement ends; no day count, no backup-specific period, nothing per record | **Verified**: supabase.com/legal/dpa, "delete all copies of Covered Data"; supabase.com/privacy: the notice "does not apply to such processing" |
| Railway logs (backend stdout) | Normal path: the account id only. **Failure path:** a database error inside `resolve_account` reaches uvicorn's unhandled-exception log, and one inside `delete_account` is logged by `logger.exception`; SQLAlchemy used to print bound parameters in the exception text, so such a line could carry the email (`resolve_account`) or the Supabase `sub` (`delete_account` filters on `external_id`). **Fixed 2026-11-09:** both engines in `database.py` and the Alembic engine in `migrations/env.py` set `hide_parameters=True`, so the text reads `[SQL parameters hidden due to hide_parameters=True]` | Hobby plan: 7-day log history | **Verified**: railway.com/workspace/plans shows "You're on the Hobby Plan" and "7-Day Log History"; docs.railway.com/observability/logs: Hobby 7 days; parameter printing reproduced locally (SQLAlchemy 2.1.8, `[parameters: (...)]`); the fix is covered by `HiddenParameterTests` in `tests/infrastructure/persistence/test_sql_adapters.py`. Lines written before the fix deployed may still hold identifiers until Railway drops them. The same docs page says upgrading "will immediately restore logs" past the window, so Railway keeps logs longer than it shows: real deletion time **unverified**. Whether such a line exists today **unverified** (logs not searched) |
| Redis: runs | Run records and the owner index | Deleted at once; a missed one expires within `RUN_TTL_SECONDS` (3600 s) | **Verified** in code: `run_repository.py` `delete_for_owner`, `ex=run_ttl_seconds` |
| Redis: arq job/result keys | `run_id`, `source_url`, `source_key`, the job result; no owner, email or account id | arq `keep_result` 3600 s | **Verified**: `job_queue.py` enqueue args; arq 0.28.0 `Worker.__init__` default `keep_result=3600` |
| Redis: rate-limit counters | Key `account:<account id>` (internal UUID, not the email) | Expires with its window (1 h and 1 min limits) | **Verified** key shape in `domain/policies.py` `quota_key`; the expiry is the `limits` library's fixed window, not read from its source |
| Redis: free runs, daily cap, BYOK vault | Free runs keyed by device id and a SHA-256 of the IP (not the account); daily cap a count only; BYOK key per run | 48 h (`free_run_allowance.py`, `daily_budget.py`); BYOK 900 s, single-use (`key_vault.py`) | **Verified** in code. None is keyed by account |
| Browser | History (IndexedDB) and the BYOK key | Until the person clears them | By design; see `docs/frontend/auth-sign-in.md` |

Upper bound on the Supabase side: about 7 days (backups, Auth logs), if Supabase destroys what it stops showing. Railway: 7 days shown, kept longer for an unstated period. What would close the gaps: Supabase support on destruction of expired daily backups and logs; Railway support on the real Hobby log deletion period. (`hide_parameters=True` on the engine, the third item, is done.)

## API keys

- The format is `vl_live_` followed by `secrets.token_urlsafe(32)`, which is 43 base64url characters.
- Only the SHA-256 hex is stored. SHA-256 rather than a slow hash because 256 random bits make brute force irrelevant, and a slow hash would add latency to every agent call.
- `prefix` is `vl_live_` plus the first 8 random characters, kept in clear so a listing is recognisable.
- The cap is `API_KEYS_PER_WORKSPACE` active keys (default 10). The SQL adapter enforces it inside the insert transaction, locking the workspace row on Postgres, so concurrent creations cannot overshoot. Hitting the cap gives a 409.
- `last_used_at` is written at most once a minute per key, so an agent polling a run does not turn every read into a database write.
- Default scopes are `runs:write` and `runs:read`. They are stored but not yet enforced per route.
- The secret never appears in logs, job arguments or listings.

## Storage

The identity data lives in Postgres (Supabase), not in Redis. The four tables are:

- `accounts`: `id`, `external_id` (unique; the IdP `sub`), `email`, `default_workspace_id`, `created_at`.
- `workspaces`: `id`, `name`, `owner_account_id` (FK), `created_at`.
- `workspace_members`: (`workspace_id`, `account_id`) PK, `role`.
- `api_keys`: `id`, `workspace_id` (FK, indexed), `name`, `prefix`, `key_hash` (unique), `scopes` (JSON), `active`, `last_used_at`, `revoked_at`, `created_at`.

Since 2026-11-13 two more tables sit beside them for signed-in free runs (migration `0003_account_free_runs`, see `free-runs.md`): `account_free_runs` (`account_id` FK cascade, `period` `YYYY-MM`, `used`; PK `(account_id, period)`) and `account_free_run_holds` (`run_id` PK, `account_id` FK cascade, `period`, `created_at`). RLS and the backend role's policy and grants as for the four above.

Runs and history are unchanged for free and anonymous callers. The server still holds runs for `RUN_TTL_SECONDS` only, and history stays in the browser. Since 2026-11-14 a paid account's results are also saved in `saved_runs`, and `accounts` gains `deleted_at`, `purge_at` and `saved_runs_expire_at` (migration `0006_saved_history`, `saved-history.md`).

### Which adapter is wired (`container.py`)

| `DATABASE_URL` | Mode | Account store |
|---|---|---|
| set | any | `SqlAccountDirectory` / `SqlApiKeyRepository` |
| blank | local (no `REDIS_URL`) | in-memory: works, but is lost on restart (dev and tests) |
| blank | distributed | **disabled**. Tokens still resolve to a bare `user:<sub>` principal (exactly as before phase 1), `/api/me` reports `accounts_enabled: false` with no workspace, and `/api/keys` returns 503 |

Two details on the URL:

- `DATABASE_URL` accepts `postgres://`, `postgresql://` or `sqlite://`, and is normalised to the async driver.
- **A distributed deployment refuses to start with a SQLite `DATABASE_URL`** (`Settings.distributed_database_error`, checked in the lifespan next to the CORS-wildcard and object-storage refusals). Each replica would keep its own file, so a key minted on one would 401 on the next.
- For Supabase, use the **transaction pooler** URL (port 6543). The engine sets asyncpg's `statement_cache_size=0` and gives each prepared statement a unique name, because Supavisor does not keep prepared statements between transactions.

### Migrations (a release step, not run at startup)

```bash
cd backend
DATABASE_URL=postgresql://postgres.<ref>:<pw>@aws-<n>-<region>.pooler.supabase.com:6543/postgres \
  alembic upgrade head
```

The pooler host is per project (`aws-0-…` or `aws-1-…`; both resolve in `us-east-2` but only one knows a given tenant; the other answers `tenant/user … not found`). Copy it from the dashboard's Connect panel, Transaction pooler tab, rather than guessing. For `videolens-dev` it is `aws-0-us-east-2.pooler.supabase.com`, and the pooler user is `videolens_api.pjekwwiaocywdbwqgtgl` (role dot project ref). When there is no shell with the `postgres` password to hand, `alembic upgrade head --sql` renders the same script and it can be run through the Supabase connector's `execute_sql` or pasted into the dashboard SQL editor; that is how `videolens-dev` was migrated on 2026-11-08 (role first, then the rendered script, then `alembic_version` inserted by the script itself). Verified afterwards by logging in as `videolens_api` through the pooler: the four tables are readable, `alembic_version` and `auth.users` are refused. Supabase also turned on RLS for `alembic_version`, which the migration does not do itself; harmless, since only `postgres` (the owner) touches it.

Run it as `postgres`, after creating the backend's own role. The role name is `DATABASE_APP_ROLE`, default `videolens_api`. **On Postgres the migration fails before creating anything if that role does not exist**, naming `DATABASE_APP_ROLE`; create the role and run it again:

```sql
CREATE ROLE videolens_api LOGIN PASSWORD '<strong password>';
```

On Postgres, `0001_identity` also does the following:

- It enables RLS on all four tables, so Supabase's `anon`/`authenticated` REST roles see nothing.
- It grants that role `USAGE` on `public`, CRUD on each table, and a `FOR ALL TO videolens_api USING (true)` policy per table. Without the policy, RLS would block the backend's own non-owner role too. (It used to skip these with a NOTICE when the role was missing. asyncpg drops notices unless a listener is registered, so the skip was silent, Alembic recorded head anyway, and every signed-in request would later have failed with permission denied. Hence the hard failure.)
- It grants `USAGE ON SCHEMA auth` plus `SELECT (id), DELETE ON auth.users` for phase 3 account deletion. A refusal does not fail the migration, but afterwards `has_table_privilege(role, 'auth.users', 'DELETE')` is checked and a missing privilege is reported at WARNING in the log and on Alembic's stdout. **Verified 2026-11-08 against `videolens-dev`: the grant does not take.** Supabase's `postgres` holds `DELETE` on `auth.users` with `is_grantable = NO` (only `SELECT` is grantable), so the statement "succeeds" with a server WARNING and `videolens_api` ends up without `DELETE`. Phase 3 therefore deletes `auth.users` rows through `videolens_private.delete_auth_user(uuid)`, a `SECURITY DEFINER` function that `0002_auth_user_deleter` creates (see *Account deletion*), so the backend still holds no Supabase API key.
- `migrations/env.py` registers an asyncpg log listener, so server NOTICEs and WARNINGs raised during a migration are printed rather than dropped.
- `alembic upgrade head --sql` (offline) renders the script without the role and privilege checks, since there is no connection to ask.

To render only `0002` for a database already at `0001_identity` (it ends with the `alembic_version` update), point `DATABASE_URL` at any Postgres URL (offline mode never connects) and give the range:

```bash
cd backend
DATABASE_URL=postgresql://offline@localhost/offline GEMINI_API_KEY=k \
  alembic upgrade 0001_identity:0002_auth_user_deleter --sql > phase3.sql
```

Apply it as `postgres` (SQL editor or connector), then check that `SELECT has_function_privilege('videolens_api', 'videolens_private.delete_auth_user(uuid)', 'EXECUTE'), has_function_privilege('videolens_api', 'videolens_private.auth_user_exists(uuid)', 'EXECUTE');` returns true twice, and that `videolens_private` is not in the project's exposed schemas.

The deployed `DATABASE_URL` then uses `videolens_api`, not `postgres`. The Dockerfile does not copy `migrations/`, so run Alembic from a checkout.

## Rate limiting and quota

`rate_limiter.quota_key` keys on `request.state.principal`. slowapi's decorator checks the limit inside the endpoint wrapper, after FastAPI has resolved the dependencies. This contradicts the plan's assumption, and was verified in the slowapi source.

- A person gets `account:<account_id>`, so one bucket survives hourly token refreshes. Without an account store it falls back to the stable `user:<sub>`.
- An API key spends from its workspace owner's `account:<id>`, so ten keys share one quota.
- An anonymous caller gets `ip:<ip>`.
- A request with no resolved principal falls back to the old header key: the token hash, else the IP.

Since 2026-11-13 a signed-in caller with an account (JWT or API key) and no BYOK key is admitted against the account's free runs (`FREE_RUNS_PER_ACCOUNT_DAILY`, default 10 per UTC day since 2026-11-14; it was 10 per month) instead of the device counter, in `CreateRunUseCase._admit`. See `free-runs.md`, "Signed-in free runs". BYOK and `DAILY_RUN_CAP` are unchanged. See `cost-abuse-protection.md`.

Since 2026-11-13 the same principal also picks the media limits: signed in (JWT or account API key) and sending `X-Gemini-Api-Key` allows 10 minutes / 500 MB (`SIGNED_IN_BYOK_MAX_*`), everyone else 3 minutes / 200 MB. At most one run above the standard limits per account is in flight, keyed on `account_id` (else the subject); a second is 429 `long_run_in_progress`. `GET /api/limits` (no auth) reports both sets. See `media-validation.md`, "Limits per caller".

## Capability

The `auth` row in `/api/capabilities` is how the frontend learns whether to offer sign-in:

- **`disabled`**: unconfigured (`probed=false`).
- **`ok`**: the JWKS was fetched and holds at least one key.
- **`degraded`**: the fetch failed or the key set was empty. Anonymous use keeps working.

The probe uses the verifier's own caching client, and the capability result is itself cached for 10 seconds.

The `database` row (`DatabaseProbe`, after `auth`) says whether the account store answers: `disabled` when `DATABASE_URL` is blank (`probed=false`), `ok` on a `SELECT 1` within 5 s, `degraded` otherwise (anonymous use keeps working; the exception class goes to `log_detail`). See `capabilities.md`.

## Tests

- `tests/infrastructure/auth/test_jwt_verifier.py`: claim rules (expired, leeway, audience on/off/missing, issuer, missing `sub`/`exp`/`iat`, wrong key, HS256 refused), the ES256 Supabase shape, and the log carrying the `kid` but not the token.
- `tests/application/test_identify_caller.py`: the three methods, `vl_live_` bearer routing, `X-Api-Key` precedence, revoked/unknown/orphan keys, malformed client id, `allow_anonymous` off, and a disabled directory behaving like before.
- `tests/application/test_api_keys.py`: create/list/revoke, the cap, the API-key 403, the non-owner 403, cross-workspace 404, no account store 503, and the `/api/me` entitlement.
- `tests/domain/test_policies.py`: `quota_key`, `can_access_run`, `looks_like_api_key`.
- `tests/infrastructure/persistence/test_sql_adapters.py`: one behaviour suite run against SQLite (aiosqlite) and the in-memory adapters, covering account bootstrap, email update, key issue/authenticate/revoke, the cap, and the `last_used_at` throttle. Also hash-only storage, URL normalisation, and an Alembic upgrade/downgrade on a temp file.
- `tests/infrastructure/health/test_probes.py`: `AuthProbe` states.
- `tests/interface/api/test_account_routes.py`: the 401/403 matrix, both key headers, a revoked key, the 409 cap, the 503 when unconfigured, and the CORS preflight.
- `tests/interface/api/test_rate_limiter.py`: the principal-based bucket and the header fallback.
- `tests/application/test_delete_account.py`: order (runs, rows, identity last), only the person's runs go, API-key 403, no store 503, row failure keeps the identity, identity failure after rows, run-store failure does not stop it, repeat calls, skipped identity step; end to end over the in-memory adapters.
- `tests/infrastructure/persistence/test_account_deleter.py`: one suite on SQLite and in-memory (the person's rows go, another person's account, workspace, key and owner membership stay, the person's membership in someone else's workspace goes, revoked keys go, repeat delete is False); the SQL transaction rolls back on a mid-way failure; the Postgres identity step calls the definer function with the UUID and skips a non-UUID subject; `0002` with Alembic mocked (DDL, revoke before grant, missing role, `has_function_privilege` false, REST role with schema USAGE, offline, SQLite no-op, downgrade order, role-name validation).
- `tests/infrastructure/persistence/test_run_repository.py::DeleteForOwnerTests`, `tests/infrastructure/health/test_probes.py::DatabaseProbeTests`, and the `DELETE /api/me` cases in `test_account_routes.py` (401, 403 for both key headers, 204 with no body, 503, readable 500; after a complete deletion the same token gets 401 on `DELETE /api/me`, `GET /api/me` and `POST /api/keys`; a retry after an identity-step failure is 204).
- Review fix (2026-11-09): `test_account_deleter.py::SqlFirstSightTests` / `InMemoryFirstSightTests` (a gone user is 401 with no rows written; first sight asks once, later reads never ask; an existing account with a gone user still reads), `IdentityProviderUsersTests` (Postgres calls `auth_user_exists`, non-UUID is gone without a query, SQLite and in-memory always present), the 0002 tests for the second function, its grants, both verify checks and its downgrade; `test_api_keys.py` key creation refused once the user is gone.

- `tests/infrastructure/persistence/test_sql_adapters.py::PostgresMigrationPathTests`: the Postgres branch with Alembic mocked (missing role fails before DDL, grants/RLS/policies applied, missing `auth.users` DELETE warns without failing, offline rendering, role-name validation).
- `tests/infrastructure/auth/test_jwt_verifier.py::JwksRefreshThrottleTests`: an unknown `kid` forces at most one refetch per window, a rotated key is picked up, and a missing `kid`, a bad `alg` or a malformed token never fetch.
- `tests/infrastructure/test_config.py::DistributedDatabaseTests`: the SQLite refusal.

The application code has not yet run against a real Supabase project: the SQL adapters are exercised on SQLite in tests, and the Postgres migration branch is tested with mocks. What *has* run for real (2026-11-08, `videolens-dev`): the offline-rendered `0001_identity` script as `postgres`, and a login as `videolens_api` through the pooler (see *Migrations*). The dashboard side is also configured (OTP expiry 600 s, `{{ .Token }}`-only templates for *Magic link or OTP* and *Confirm sign up*, site URL and redirect allowlist for the dev frontend and `localhost:3005`), and the four `AUTH_*`/`DATABASE_URL` variables are set on the Railway `dev` backend service. The first end-to-end check (the `auth` capability on dev `/health`, then a real token against `/api/me`) happens once the branch is merged into `dev`. State and values live in `docs/auth-plan.md`, "Phase 0 state".

## Known issues

- `/api/free-runs` resolves a principal only when a credential is sent (`get_optional_signed_in_principal`, since 2026-11-13), so signed-in callers' reads are bucketed per account; anonymous callers still use the header fallback (IP). An invalid credential there is a 401, as on `/api/me`.
- The JWKS cache-expiry fetch (every 10 minutes) is not throttled beyond PyJWT's own cache. If the identity provider is down, each token request still makes one fetch attempt, capped at the 5-second timeout.

## Changelog
- 2026-11-07 · security-check · `JwtVerifier` reuses one caching `PyJWKClient`; first tests for the verifier
- 2026-11-08 · main session · phase 0 check against `videolens-dev` (ref `pjekwwiaocywdbwqgtgl`, `us-east-2`, Postgres 17.11): signing key already ES256; `auth.users` DELETE is not grantable by `postgres`, so phase 3 needs a `SECURITY DEFINER` helper; pooler host and SQL-editor migration path documented
- 2026-11-08 · main session · `videolens_api` role created and `0001_identity` applied on `videolens-dev` through the connector; verified role login via `aws-0-us-east-2` pooler, grants, RLS and policies; `auth.users` grant confirmed not taken
- 2026-11-08 · main session · dashboard Auth settings and Railway `dev` variables done; "not run against a real project" paragraph narrowed to the application code; end-to-end check deferred to the `dev` merge
- 2026-11-08 · backend subagent (auth phase 1) · rewritten as the implemented reference. Covers `IdentifyCallerUseCase` (API key, then bearer, then client id); accounts, workspaces and API keys in Postgres via SQLAlchemy and Alembic, with in-memory or disabled fallbacks; `/api/me` and `/api/keys`; `require_person`; the stricter JWT rules (leeway, required claims, optional audience); account-keyed quota; the `auth` capability. Absorbs the parked branch's accounts-workspaces and api-keys docs
- 2026-11-08 · backend subagent (auth phase 1, review fixes) · JWT header screened before key lookup and unknown-kid JWKS refetches throttled to one per 60 s (5 s fetch timeout); `role: authenticated` required and `is_anonymous` refused; case-insensitive `Bearer`; distributed mode refuses a SQLite `DATABASE_URL`; the migration fails on a missing backend role instead of a silent NOTICE, checks the `auth.users` DELETE privilege and warns loudly, and `env.py` surfaces server notices; Known issues section added
- 2026-11-09 · backend subagent (auth phase 3) · `DELETE /api/me` (deletion order, idempotency, where the identity step is skipped), migration `0002_auth_user_deleter` and why it is a `SECURITY DEFINER` function, offline render of 0002 alone, the `database` capability, phase 3 tests
- 2026-11-09 · backend subagent (auth phase 3, review fix) · a still-valid token can no longer re-create a deleted account or mint an unrevocable key: `IdentityProviderUsers` port, `videolens_private.auth_user_exists(uuid)` added to 0002 (edited in place, never applied), checked on first sight of a subject and before key issue; a second `DELETE /api/me` after a complete deletion is now 401, not 204; idempotency wording, SQL block, verify checks and tests updated
- 2026-11-09 · research subagent · "Data after account deletion": what survives deletion and for how long (Supabase backups and PITR, auth.* cascades and flow_state, audit log table off, Supabase and Railway log retention, DPA, Redis keys), each row marked verified or unverified with evidence; the SQLAlchemy parameters-in-traceback leak to Railway logs noted
- 2026-11-09 · backend subagent (log hygiene) · engine hides bound parameters in error text
- 2026-11-09 · main session · 0002 applied to `videolens-dev` and verified: `alembic_version` at `0002_auth_user_deleter`, `videolens_api` has EXECUTE on both functions, `anon`/`authenticated` have no EXECUTE and no USAGE on `videolens_private`, both functions SECURITY DEFINER owned by `postgres` with empty search_path; status lines updated to committed
- 2026-11-13 · backend agent · signed-in free runs: the two `0003_account_free_runs` tables in Storage and in the deletion table, `_admit` now reads the account, `/api/free-runs` resolves an optional principal (known issue narrowed)
- 2026-11-13 · backend agent · signed-in BYOK media limits (600 s / 500 MB) and the one-long-run-per-account guard, both keyed on the resolved principal
- 2026-11-13 · backend agent · account deletion cancels the Stripe subscription first and refuses (503 `subscription_cancel_failed`) when it cannot; `Plan.PAID` on `/api/me` for a paid account; migration 0004 adds the three billing tables beside the identity tables
- 2026-11-14 · backend agent · signed-in free runs are per UTC day (`FREE_RUNS_PER_ACCOUNT_DAILY`); migration `0005_account_daily_free_runs` widens `period` on the two counter tables
- 2026-11-14 · backend agent · account deletion is a 30-day hold (`DELETE /api/me` returns 200 with `purge_at`; 410 `account_pending_deletion` everywhere but the new `POST /api/me/restore`; API keys 401 while held); the hourly worker cron removes the Supabase user then the rows after the hold; `saved_history` on `/api/me`; migration 0006 columns in Storage
