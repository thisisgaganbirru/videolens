# Authentication, accounts and API keys

Every request resolves to one `Principal`: an anonymous browser, a signed-in
person (a Supabase access token), or an agent holding an API key. Phase 1 of
`docs/auth-plan.md` (backend identity) is implemented on `feat/auth-supabase`.
It is pending a PR, and no frontend sign-in exists yet (that is phase 2).

## Files

| Layer | File | What |
|---|---|---|
| domain | `entities.py` | `AuthMethod`, `Principal` (+ `method`, `account_id`, `workspace_id`, `email`, `owner_id`), `Account`, `Workspace`, `WorkspaceRole`, `ApiKey`, `ApiKeyCreated` |
| domain | `entitlements.py` | `Plan.FREE` only, `Entitlement`, `entitlement_for` |
| domain | `policies.py` | `is_valid_client_id`, `looks_like_api_key` (`vl_live_`), `can_access_run`, `quota_key`, `quota_key_from_headers` (fallback) |
| domain | `errors.py` | `AuthenticationError` 401, `ForbiddenError` 403, `ApiKeyNotFoundError` 404, `ApiKeyLimitError` 409, `ClientIdInvalidError` 400, `AuthNotConfiguredError` / `AccountsNotConfiguredError` 503 |
| domain | `ports.py` | `TokenVerifier`, `AccountDirectory`, `ApiKeyRepository` |
| application | `identify_caller.py` | `IdentifyCallerUseCase`: the whole credential precedence |
| application | `entitlements.py`, `get_account.py` | `EntitlementResolver.for_principal`, `GetAccountUseCase` (`/api/me`) |
| application | `api_key_access.py`, `create_api_key.py`, `list_api_keys.py`, `revoke_api_key.py` | key management and its gate |
| infrastructure | `auth/jwt_verifier.py` | `JwtVerifier` (PyJWT, one caching `PyJWKClient`) |
| infrastructure | `persistence/database.py`, `schema.py` | async engine (asyncpg / aiosqlite), the four tables |
| infrastructure | `persistence/account_directory.py`, `api_key_repository.py` | SQL and in-memory adapters |
| infrastructure | `health/probes.py` | `AuthProbe` (`auth` capability) |
| interface | `api/dependencies.py` | `get_principal`, `get_signed_in_principal`, `require_person` |
| interface | `api/routes.py`, `schemas.py` | `GET /api/me`, `GET|POST /api/keys`, `DELETE /api/keys/{id}` |
| migrations | `backend/alembic.ini`, `backend/migrations/` | `0001_identity` |

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
- `require_person`: a signed-in person only. Anonymous gets 401 and an API key gets 403, so a leaked agent key cannot mint more keys. Used by all `/api/keys` routes and, in phase 3, by account deletion.

A 401 carries `WWW-Authenticate: Bearer`.

## Endpoints

| Route | Who | Returns |
|---|---|---|
| `GET /api/me` | person or key | `subject`, `method`, `email`, `account_id`, `workspace {workspace_id, name}`, `entitlement {plan, max_duration_seconds, max_file_size_mb, metered, api_access, library}`, `accounts_enabled` |
| `GET /api/keys` | person (workspace owner) | `{keys: [...]}`, newest first, including revoked keys (`active: false`, `revoked_at`) |
| `POST /api/keys` `{name}` | person (workspace owner) | 201 with the key and its `secret`, shown once. Names are trimmed to 80 characters and default to "Unnamed key" |
| `DELETE /api/keys/{key_id}` | person (workspace owner) | 204. A key from another workspace or an unknown key gets 404 |

The entitlement is the single free plan at the deployment's limits (`MAX_VIDEO_DURATION_SECONDS`, `MAX_FILE_SIZE_MB`), with `metered=false`, `api_access=true` and `library=false`. There is no plan gate on API keys.

CORS lists `Authorization`, `Content-Type`, `X-Api-Key`, `X-Client-ID`, `X-Gemini-Api-Key` and `X-Device-Token`, and allows `DELETE`.

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

Runs and history are unchanged. The server still holds runs for `RUN_TTL_SECONDS` only, and history stays in the browser.

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
DATABASE_URL=postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:6543/postgres \
  alembic upgrade head
```

Run it as `postgres`, after creating the backend's own role. The role name is `DATABASE_APP_ROLE`, default `videolens_api`. **On Postgres the migration fails before creating anything if that role does not exist**, naming `DATABASE_APP_ROLE`; create the role and run it again:

```sql
CREATE ROLE videolens_api LOGIN PASSWORD '<strong password>';
```

On Postgres, `0001_identity` also does the following:

- It enables RLS on all four tables, so Supabase's `anon`/`authenticated` REST roles see nothing.
- It grants that role `USAGE` on `public`, CRUD on each table, and a `FOR ALL TO videolens_api USING (true)` policy per table. Without the policy, RLS would block the backend's own non-owner role too. (It used to skip these with a NOTICE when the role was missing. asyncpg drops notices unless a listener is registered, so the skip was silent, Alembic recorded head anyway, and every signed-in request would later have failed with permission denied. Hence the hard failure.)
- It grants `USAGE ON SCHEMA auth` plus `SELECT (id), DELETE ON auth.users` for phase 3 account deletion. A refusal does not fail the migration (phase 3 can grant it from the dashboard), but afterwards `has_table_privilege(role, 'auth.users', 'DELETE')` is checked and a missing privilege is reported at WARNING in the log and on Alembic's stdout, with the SQL to run. That also catches a GRANT that "succeeds" with only a server WARNING (no grant option). **Unverified:** whether Supabase lets `postgres` grant on `auth.users` has not been tested against a real project.
- `migrations/env.py` registers an asyncpg log listener, so server NOTICEs and WARNINGs raised during a migration are printed rather than dropped.
- `alembic upgrade head --sql` (offline) renders the script without the role and privilege checks, since there is no connection to ask.

The deployed `DATABASE_URL` then uses `videolens_api`, not `postgres`. The Dockerfile does not copy `migrations/`, so run Alembic from a checkout.

## Rate limiting and quota

`rate_limiter.quota_key` keys on `request.state.principal`. slowapi's decorator checks the limit inside the endpoint wrapper, after FastAPI has resolved the dependencies. This contradicts the plan's assumption, and was verified in the slowapi source.

- A person gets `account:<account_id>`, so one bucket survives hourly token refreshes. Without an account store it falls back to the stable `user:<sub>`.
- An API key spends from its workspace owner's `account:<id>`, so ten keys share one quota.
- An anonymous caller gets `ip:<ip>`.
- A request with no resolved principal falls back to the old header key: the token hash, else the IP.

The free-run and BYOK rules are unchanged (`create_run.py` untouched). See `cost-abuse-protection.md`.

## Capability

The `auth` row in `/api/capabilities` is how the frontend learns whether to offer sign-in:

- **`disabled`**: unconfigured (`probed=false`).
- **`ok`**: the JWKS was fetched and holds at least one key.
- **`degraded`**: the fetch failed or the key set was empty. Anonymous use keeps working.

The probe uses the verifier's own caching client, and the capability result is itself cached for 10 seconds.

## Tests

- `tests/infrastructure/auth/test_jwt_verifier.py`: claim rules (expired, leeway, audience on/off/missing, issuer, missing `sub`/`exp`/`iat`, wrong key, HS256 refused), the ES256 Supabase shape, and the log carrying the `kid` but not the token.
- `tests/application/test_identify_caller.py`: the three methods, `vl_live_` bearer routing, `X-Api-Key` precedence, revoked/unknown/orphan keys, malformed client id, `allow_anonymous` off, and a disabled directory behaving like before.
- `tests/application/test_api_keys.py`: create/list/revoke, the cap, the API-key 403, the non-owner 403, cross-workspace 404, no account store 503, and the `/api/me` entitlement.
- `tests/domain/test_policies.py`: `quota_key`, `can_access_run`, `looks_like_api_key`.
- `tests/infrastructure/persistence/test_sql_adapters.py`: one behaviour suite run against SQLite (aiosqlite) and the in-memory adapters, covering account bootstrap, email update, key issue/authenticate/revoke, the cap, and the `last_used_at` throttle. Also hash-only storage, URL normalisation, and an Alembic upgrade/downgrade on a temp file.
- `tests/infrastructure/health/test_probes.py`: `AuthProbe` states.
- `tests/interface/api/test_account_routes.py`: the 401/403 matrix, both key headers, a revoked key, the 409 cap, the 503 when unconfigured, and the CORS preflight.
- `tests/interface/api/test_rate_limiter.py`: the principal-based bucket and the header fallback.

- `tests/infrastructure/persistence/test_sql_adapters.py::PostgresMigrationPathTests`: the Postgres branch with Alembic mocked (missing role fails before DDL, grants/RLS/policies applied, missing `auth.users` DELETE warns without failing, offline rendering, role-name validation).
- `tests/infrastructure/auth/test_jwt_verifier.py::JwksRefreshThrottleTests`: an unknown `kid` forces at most one refetch per window, a rotated key is picked up, and a missing `kid`, a bad `alg` or a malformed token never fetch.
- `tests/infrastructure/test_config.py::DistributedDatabaseTests`: the SQLite refusal.

Nothing here has run against a real Supabase project or Postgres. The SQL is exercised on SQLite, and the Postgres-only migration branch was only rendered offline and tested with mocks.

## Known issues

- `/api/free-runs` has no `get_principal` dependency, so its rate-limit bucket still comes from the header fallback (token hash, else IP), not the account. This predates phase 1 and was judged below threshold in review.
- The JWKS cache-expiry fetch (every 10 minutes) is not throttled beyond PyJWT's own cache. If the identity provider is down, each token request still makes one fetch attempt, capped at the 5-second timeout.

## Changelog
- 2026-11-07 · security-check · `JwtVerifier` reuses one caching `PyJWKClient`; first tests for the verifier
- 2026-11-08 · backend subagent (auth phase 1) · rewritten as the implemented reference. Covers `IdentifyCallerUseCase` (API key, then bearer, then client id); accounts, workspaces and API keys in Postgres via SQLAlchemy and Alembic, with in-memory or disabled fallbacks; `/api/me` and `/api/keys`; `require_person`; the stricter JWT rules (leeway, required claims, optional audience); account-keyed quota; the `auth` capability. Absorbs the parked branch's accounts-workspaces and api-keys docs
- 2026-11-08 · backend subagent (auth phase 1, review fixes) · JWT header screened before key lookup and unknown-kid JWKS refetches throttled to one per 60 s (5 s fetch timeout); `role: authenticated` required and `is_anonymous` refused; case-insensitive `Bearer`; distributed mode refuses a SQLite `DATABASE_URL`; the migration fails on a missing backend role instead of a silent NOTICE, checks the `auth.users` DELETE privilege and warns loudly, and `env.py` surfaces server notices; Known issues section added
