# Authentication and authorization plan

Design for adding real user identity to VideoLens with Supabase Auth, while
keeping anonymous usage exactly as it is today. This is what the paid tier
will later stand on; plans, billing and entitlement values are out of scope
here and get their own document when that work starts. Cross-cutting
(backend, frontend, Android, agents, infra), so it is filed at the top of
`docs/` like `railway-environments.md`.

Status: phase 1 implemented on feat/auth-supabase (pending PR). Phases 2 and 3 are not started. The implemented reference, with the deviations from this plan, is `docs/backend/auth.md`.

## The situation this plan starts from

Two things shape it, and the second was only found while writing it.

First, the backend on `dev` already verifies OIDC bearer tokens.
`backend/app/infrastructure/auth/jwt_verifier.py` fetches a JWKS from
`AUTH_JWKS_URL` (one cached `PyJWKClient`, fixed 2026-11-07) and verifies
RS256/ES256 tokens against `AUTH_ISSUER` and `AUTH_AUDIENCE`.
`interface/api/dependencies.py` turns that into
`Principal(subject="user:<sub>", authenticated=True)` or falls back to
`client:<X-Client-ID>`. Ownership of runs is the only authorization rule.
The frontend has no auth port, hook or panel. Anonymous callers are
additionally governed by the free-run allowance (`docs/backend/free-runs.md`,
landed 2026-11-01), which is device-token based and independent of identity.

Second, there is a complete, unmerged implementation of accounts on
`origin/feat/paid-tier-integration` (last commit 2026-09-17, 7 commits, now
123 commits behind `dev`, conflicts in `CLAUDE.md`, `DEPLOYMENT.md`,
`README.md`, `backend/.env.example` and `backend/app/application/
create_run.py`). It contains, in one bundle:

- Identity: `IdentifyCallerUseCase` (API key, then JWT, then client id), an
  extended `Principal` (`method`, `account_id`, `workspace_id`, `plan`,
  `email`), `accounts` / `workspaces` / `workspace_members` tables, API keys
  (`vl_live_` prefix, hashed, `X-Api-Key` or bearer), `GET /api/me`,
  `GET|POST|DELETE /api/keys`, SQLAlchemy async + Alembic, SQLite for tests.
- Everything the owner has asked to do separately: `Plan` enum with four
  tiers, `Entitlement` table, minutes metering, Stripe checkout, portal and
  webhook, a Postgres run archive (`TieredRunRepository`), library search,
  the `product-plan-100k.md` roadmap.
- Frontend: `AuthSession` port with a `ClerkAuthSession` adapter (dynamic
  `import("@clerk/clerk-js")`, `openSignIn()` modal), `NullAuthSession`
  when unconfigured, `apiClient.ts` adding `Authorization: Bearer` to every
  request, `AccountPanel` with plan cards and the API-key UI, `useAuthSession`,
  `useAccount`, `useApiKeys`, a `LibraryPanel`.
- `mcp/` with `VIDEOLENS_API_KEY` support (a newer copy than the one on
  `feature/mcp-server`, which is what `CLAUDE.md` currently describes; see
  `engineering-standards.md`).

The backend on that branch is already provider-agnostic: nothing in
`backend/` names Clerk. Clerk lives in exactly one frontend file and one
environment variable. That is the whole reason the Supabase switch is cheap.

## Decisions

1. Identity provider is Supabase Auth, one project per Railway environment:
   `videolens-dev` (branch `dev`, Railway `dev`) now, and `videolens-prod`
   (`main`, Railway `production`) when billing is close (resolved question
   5). The owner creates them; project administration goes through the
   Supabase connector (MCP) and the dashboard, not the Supabase CLI
   (decided 2026-11-08, see "Tooling" below). No project credentials in
   the repo. Production keeps the variables blank until then, which is the
   anonymous-only behaviour it has today.
2. The backend stays provider-agnostic: JWKS verification only, no Supabase
   SDK, no Supabase REST keys on Railway. Supabase is the token issuer and
   the host of a Postgres the backend owns through its own migrations.
3. The frontend uses `supabase-js` for auth only. All data goes through
   FastAPI, so web, Android and terminal agents share one API surface.
4. Anonymous use stays first-class. `ALLOW_ANONYMOUS` stays `true` in every
   environment; `X-Client-ID`, the device token and the free-run allowance
   are untouched. Signing in is opt-in.
5. Reuse the identity slice of `feat/paid-tier-integration` rather than
   redesigning it. Lift it onto a fresh branch from current `dev`, replace
   the Clerk adapter with a Supabase one, and leave plans, Stripe, metering,
   the archive and library on the old branch for the subscription work. The
   reasoning is in the next section.
6. Subscriptions are separate and later. This plan keeps the branch's
   `EntitlementResolver` seam but with one plan (`FREE`) and no metering, so
   the later work replaces a table of numbers, not a structure.

## Why lift the branch instead of merging it or starting over

Merging it whole drags Stripe, metering and the archive into `dev` before
the owner wants them, and the hardest conflict is in `create_run.py`, where
the branch's entitlement check and `dev`'s free-run `_admit` both rewrote the
admission order. Resolving that conflict means deciding how plans and free
runs interact, which is subscription design, not auth.

Starting over throws away a backend design that already fits
`ARCHITECTURE.md` (use case per operation, ports, adapters taking
`Settings`, in-memory fallbacks, SQLite-backed tests) and that was reviewed
when written. The parts worth keeping are the parts with no billing in them.

So: cherry-pick by file, not by commit. The identity files come across
mostly unchanged; `create_run.py` is not touched at all in this phase; the
plan-shaped parts are stubbed to one tier.

## Target model

### Three kinds of caller

| Kind | Credential | `Principal` | Owns |
|---|---|---|---|
| Anonymous | `X-Client-ID` (+ `X-Device-Token` for free runs) | `subject=client:<id>`, `method=ANONYMOUS` | Their Redis runs, `RUN_TTL_SECONDS` (1 hour) after the last write |
| Signed-in person | `Authorization: Bearer <Supabase JWT>` | `subject=user:<sub>`, `method=TOKEN`, `account_id`, `workspace_id`, `email` | The workspace's runs |
| Agent / script | `Authorization: Bearer vl_live_<key>` or `X-Api-Key` | `subject=key:<id>`, `method=API_KEY`, `workspace_id` | The same workspace's runs |

Runs created by a signed-in caller are owned by the workspace (the branch's
`principal.owner_id`), so a key minted in the web app and the web app itself
see one history. Every account gets one default workspace, created on first
sign-in by `AccountDirectory.resolve_account`. Workspaces are not shown in
the UI in this phase; they exist so API keys and, later, seats have a home
without a second migration.

### Tokens

Supabase issues OIDC-shaped JWTs. The existing settings map directly:

| Setting | Value (per project) |
|---|---|
| `AUTH_JWKS_URL` | `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json` |
| `AUTH_ISSUER` | `https://<ref>.supabase.co/auth/v1` |
| `AUTH_AUDIENCE` | `authenticated` |

The branch made `AUTH_AUDIENCE` optional because Clerk's session tokens
carry no `aud`. Supabase's do, so for Supabase it is set, and the verifier
keeps enforcing it whenever it is set. A token from one of the owner's other
Supabase projects then fails on `iss` and `aud` both.

Prerequisite that is easy to miss: the verifier accepts only RS256 and ES256,
on purpose, and legacy Supabase projects sign with a shared HS256 secret. In
each new project open Authentication, then JWT Keys, and confirm the current
signing key is asymmetric (ES256 / P-256); if not, rotate before anything
else. Do not add HS256 to the verifier: a shared secret on the backend is the
coupling decision 2 avoids.

Claims read: `sub` (becomes `accounts.external_id`), `email` (display, and
kept current on `accounts.email`), `role` (`authenticated`). Nothing else.
Add `leeway=30` and `options={"require": ["exp", "iat", "sub"]}` to
`decode`, which the branch does not have.

### API keys

As on the branch, with two adjustments.

- Format `vl_live_` + 32 random bytes, base64url. The prefix routes the
  header without a database read (`looks_like_api_key`); Supabase JWTs start
  with `eyJ`.
- Stored as `sha256(secret)`; plaintext shown once. The first eight
  characters are kept so the list is recognisable.
- `X-Api-Key` and `Authorization: Bearer vl_live_...` both work. The MCP
  server uses the bearer form.
- Adjustment 1: key management (`/api/keys`) and account deletion refuse
  `method=API_KEY`. The branch's `get_signed_in_principal` only checks
  `authenticated`, which an API key satisfies; add a `require_person`
  dependency that also checks `method is TOKEN`. A leaked agent key must not
  be able to mint more keys.
- Adjustment 2: the branch gates key creation on `entitlement.api_access`,
  which only paid plans have. In this phase API access is on for everyone,
  because the stated product direction is that agents are a first-class
  client. The subscription work can turn it back into an entitlement.
- Cap of 10 live keys per workspace; `last_used_at` written at most once a
  minute.

### Authorization

Small, and named so it is testable without FastAPI:

1. Ownership: `can_access_run(principal, run)`, `run.owner_id ==
   principal.owner_id`. What `GetRunUseCase` and `ListRunsUseCase` already
   do, moved into `domain/policies.py`.
2. Credential strength: `require_person` for `/api/keys` and `DELETE
   /api/me`. Anonymous → 401, API key → 403.
3. Entitlements: `EntitlementResolver` stays, returns the single `FREE`
   entitlement with today's deployment limits (`MAX_FILE_SIZE_MB`,
   `MAX_DURATION_SECONDS`), `metered=False`, `api_access=True`,
   `library=False`. `GET /api/me` returns it so the frontend renders limits
   from the server. `Plan` keeps only `FREE` in this phase; the other three
   values come back with the pricing work.

Roles: Supabase `app_metadata.roles` is reserved for an `admin` value the
owner can set in the dashboard. Nothing reads it yet. `app_metadata` rather
than `user_metadata` because users can edit the latter.

### Rate limiting with real identity

`quota_key_from_headers` hashes the raw bearer token, so a signed-in user's
hourly window resets every time `supabase-js` refreshes the token (hourly by
default). Replace with `quota_key(principal, client_ip)`:

- `TOKEN` → `account:<account_id>`; `API_KEY` → `account:<owning
  account>` (ten keys are not ten quotas); `ANONYMOUS` → `ip:<client_ip>`
  as today.

slowapi's `key_func` runs before dependencies. The limiter calls the same
resolver `get_principal` uses, and on any failure falls back to the token
hash; the request will 401 a moment later anyway. JWKS is cached, so this is
not a second network call. `DAILY_RUN_CAP` and the free-run allowance stay
exactly as they are; per-account caps are an entitlement and therefore
subscription work.

Free runs and sign-in do not interact in this phase. A signed-in caller
without a Gemini key still presents a device token and still gets
`FREE_RUNS_PER_DEVICE`. This is deliberate: `_admit` is the branch's and the
free-run doc's shared "seam for paid plans", and the first thing the
subscription work decides is what signing in buys there. Until then,
`create_run.py` is not modified.

### Account lifecycle

- Sign-up is implicit. The first verified token creates `accounts` and the
  default `workspaces` row via `resolve_account`. No `auth.users` trigger,
  no FK into the `auth` schema, so the backend's schema stays portable (the
  SQLite test path depends on this).
- Account deletion is required before an Android release with sign-in:
  Google Play's account deletion policy applies as soon as an app offers
  account creation. New endpoint `DELETE /api/me` (`require_person`): delete
  the workspace's Redis runs and index, the `api_keys`, `workspace_members`,
  `workspaces` and `accounts` rows, then the Supabase user. The last step
  needs one of two things on Railway: the service-role key (to call the
  Admin API) or a Postgres role with `DELETE` on `auth.users`. The plan
  takes the role to keep decision 2 intact. Checked 2026-11-08 on
  `videolens-dev`: `postgres` holds `DELETE` on `auth.users` without grant
  option, so the direct grant in migration 0001 does not take. Phase 3 will
  instead add a `SECURITY DEFINER` function owned by `postgres` in a
  non-exposed schema, executable only by `videolens_api`, which still keeps
  Supabase keys off Railway. The frontend signs out and clears
  `localStorage` after.
- Anonymous history is not migrated on sign-in. Server-side runs live one
  hour (`RUN_TTL_SECONDS`); the durable history is the browser's IndexedDB,
  which does not move either. A `POST /api/me/claim` that re-keys runs owned
  by the presented `X-Client-ID` is a small follow-up if people miss them
  (open question 2). Decided 2026-11-08: not in this phase.

### Where data lives

| Data | Store | Notes |
|---|---|---|
| Users, sessions, OAuth identities | Supabase Auth (`auth` schema) | Provider's job |
| `accounts`, `workspaces`, `workspace_members`, `api_keys` | Supabase Postgres, `public`, owned by `backend/migrations/` (Alembic) | From the branch, minus plan and Stripe columns, which return with billing |
| Runs and results | Redis, as today | The branch's Postgres archive and `TieredRunRepository` stay on the branch; durable paid history is subscription work |
| BYOK Gemini key | Browser `localStorage` | Unchanged |
| Supabase session | Browser `localStorage` via `supabase-js` | A static export has no server to hold it |

Connection: `asyncpg` through SQLAlchemy async, as the branch has it, over
`DATABASE_URL` pointing at the Supavisor transaction pooler (port 6543), since
Railway services sleep and wake and must not pin direct connections. A
dedicated `videolens_api` role with grants on the four tables plus `DELETE`
on `auth.users`; the `postgres` superuser URL is never placed on Railway.
Row level security on with no policies on the four tables, so nothing but
the backend role touches them. The anon and service-role REST keys are not
used by the backend at all.

This is the first server-side persistence in the project. `CLAUDE.md`'s
"do not add server-side persistence" rule is about runs and history, which
stay in Redis and the browser; the four identity tables are the exception
it anticipated ("the paid tier that would need it"). The rule's wording is
updated when phase 1 lands so the two statements do not contradict.

Migrations stay Alembic (`backend/migrations/`, already written) rather than
`supabase/migrations/`: the backend owns this schema, SQLite tests need it
driver-neutral, and there is no second migration owner. The one
Supabase-specific statement (the `auth.users` grant) is raw SQL in the
Alembic migration guarded by dialect.

Tooling (decided 2026-11-08): **no Supabase CLI**. The owner tried it, it
needs its own login, a `supabase/` folder and a linked project for anything
useful, and all of that duplicated what the connector already does. The
connector runs SQL as `postgres` (role, grants, the rendered Alembic
script, read-only checks), inspects the project and advisors, and reads the
project URL and publishable key. What the connector cannot do is change
Auth settings (email OTP, redirect allowlist, site URL, providers); those
are done in the dashboard, with the agent driving the browser when asked.
Local development runs against `videolens-dev` or with the variables blank;
there is no local Supabase stack.

`DATABASE_URL` blank → in-memory `AccountDirectory` and `ApiKeyRepository`
(the branch has these), so local `uvicorn` with no Supabase still boots and
the default tests need no Postgres.

## Backend changes

Everything below is lifted from `feat/paid-tier-integration` unless marked
new or changed. Per `backend/ARCHITECTURE.md` layering.

`domain/`

- `entities.py`: `AuthMethod`, extended `Principal` with `owner_id`,
  `Account`, `Workspace`, `ApiKey`, `ApiKeyCreated`. Drop `TokenUsage` and
  the archive-only types for now.
- `entitlements.py`: `Plan` with `FREE` only, `Entitlement`,
  `entitlement_for(plan, settings)` returning deployment limits. Changed.
- `errors.py`: `AuthenticationError` (401), `ForbiddenError` (403, new),
  `ApiKeyLimitError` (409). Move `AuthNotConfiguredError` here from the
  adapter so `error_handlers.py` maps it to 503 like other domain errors.
- `policies.py`: `can_access_run` (new), `quota_key(principal, ip)`
  (changed), `looks_like_api_key` (moved from the adapter).
- `ports.py`: `AccountDirectory`, `ApiKeyRepository`, plus `AccountDeleter`
  (new).

`application/`

- `identify_caller.py`: as on the branch. `from_token_claims` no longer
  reads `plan` from the workspace.
- `entitlements.py`: `EntitlementResolver` reduced to `for_principal`.
- `get_account.py`: as on the branch, minus usage.
- `delete_account.py`: new.
- `create_api_key.py`, `list_api_keys.py`, `revoke_api_key.py`: lifted from
  the route bodies into use cases; `api_access` gate removed.
- `get_run.py`, `list_runs.py`: use `can_access_run`.
- `create_run.py`: untouched in this phase (see free runs above). The only
  change is that `owner_id` already comes from `principal.owner_id`, which
  for anonymous callers is the client subject, so nothing moves.

`infrastructure/`

- `auth/jwt_verifier.py`: add leeway and required claims; keep audience
  enforcement when set.
- `persistence/database.py`, `schema.py` (four tables), `account_directory.py`
  (no plan columns), `api_key_repository.py`: lifted. `account_deleter.py`
  new.
- `health/probes.py`: `auth` capability (configured; `probed=True` when the
  JWKS fetched) and `database` (`SELECT 1`). This is how the frontend learns
  whether to show sign-in at all (`docs/frontend/capability-reporting.md`).
- `config.py`: `database_url`, `api_keys_per_workspace: int = 10`. No Stripe
  settings.

`interface/api/`

- `dependencies.py`: as on the branch, plus `require_person`.
- `routes.py`: `GET /api/me`, `DELETE /api/me` (new), `GET|POST /api/keys`,
  `DELETE /api/keys/{id}`. No `/api/billing/*`, no `/api/library`.
- `schemas.py`: `AccountResponse` (identity + entitlement, no usage),
  `ApiKeyListResponse`, `ApiKeyCreatedResponse`. Kept separate from entities
  so nothing internal leaks, same reasoning as `RunResponse`.
- `rate_limiter.py`: `quota_key` through the resolver.
- `app.py`: list `Authorization` and `X-Api-Key` in `allow_headers`
  explicitly.

`container.py`: wires `Database`, the two repositories, the deleter, the use
cases. `requirements.in` gains `sqlalchemy[asyncio]`, `asyncpg`, `aiosqlite`,
`alembic`; not `stripe`.

## Frontend changes

Per `frontend/ARCHITECTURE.md`; nothing in `components/` touches
`supabase-js`.

`domain/`

- `entities.ts`: `AuthUser`, `AccountResponse` (no usage/plan cards),
  `ApiKeySummary`, `ApiKeyCreated`.
- `ports.ts`: `AuthSession` as on the branch, with `signIn()` replaced by
  methods a provider without a hosted modal needs:
  `requestEmailCode(email)`, `verifyEmailCode(email, code)`,
  `signInWithGoogle()`. `AccountGateway` for `/api/me` and `/api/keys`.

`infrastructure/`

- `authSession.ts`: `SupabaseAuthSession` replaces `ClerkAuthSession`.
  Built from `NEXT_PUBLIC_SUPABASE_URL` and
  `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (the `sb_publishable_` format new
  projects show first; the legacy anon JWT also works). Options:
  `persistSession: true`, `autoRefreshToken: true`, `flowType: "pkce"`,
  `detectSessionInUrl` on web only. Dynamic `import("@supabase/supabase-js")`
  for the same bundle-size reason the branch gives for Clerk.
  `NullAuthSession` and `buildAuthSession()` stay as they are. This is the
  only file where the provider changes.
- `apiClient.ts`: lifted. Adds the bearer when `getToken()` returns one and
  keeps sending `X-Client-ID` and `X-Device-Token` regardless, so the header
  set does not change shape between signed-out and signed-in requests.
- `accountGateway.ts`: lifted, minus billing methods.
- `container.ts`: `authSession`, `accountGateway`; `runsGateway` built on
  `apiClient`.

`application/`

- `useAuthSession.ts`: lifted; grows the OTP state (`email entered`, `code
  sent`, `verifying`). Follows the existing read-after-hydration pattern
  and adds one entry to the `react-hooks/set-state-in-effect` count noted in
  `CLAUDE.md` rather than inventing a new shape.
- `useAccount.ts`: lifted, minus `upgrade`/`manageBilling`.
- `useApiKeys.ts`: lifted.
- `useAnalysisRun.ts`, `useRunHistory.ts`: refetch history on auth change,
  since the owner changed.

`components/`

- `panels/AccountPanel.tsx`: lifted, then cut down. Signed out: email
  field, "send code", code field, Google button, a sentence on what signing
  in adds and that it is optional. Signed in: email, sign out, API keys
  section (create with a name, one-time secret with copy, list, revoke),
  delete account with a typed confirmation. No plan cards, no usage meter.
  Hidden when the capability report says `auth` is unavailable.
- `HomeScreen.tsx`, `AppNav.tsx`, `useMainTab.ts`: the `account` tab, as on
  the branch. No `library` tab.
- `panels/ApiKeyPanel.tsx` keeps its name (the Gemini BYOK key). VideoLens
  keys live in the Account tab so two things called "API key" do not share a
  panel.

Sign-in methods, in order:

1. Email one-time code (6 digits). Identical on web and inside the Capacitor
   WebView: no redirect, no deep link, no browser hand-off. Primary for that
   reason.
2. Google OAuth. On web, a PKCE redirect back to the app origin. On Android
   the redirect must land in the app, which needs a custom scheme
   (`ai.videolens.app://auth/callback`) in the Supabase redirect allowlist
   and `AndroidManifest.xml`, and `@capacitor/browser` to open the consent
   screen outside the WebView (Google refuses sign-in in embedded WebViews).
   The one piece with real device risk, so it ships after OTP is proven and
   is verified from the CI-built APK.

Magic links are not offered: on Android a link opens in whatever browser
handles it and the session lands outside the app.

## Android specifics

- No native code for OTP. The WebView calls Supabase Auth's REST endpoints
  like any cross-origin call; the fixed `https://localhost` origin
  (`backend/cors.md`) is irrelevant to Supabase, which does not check
  origins on its public auth endpoints.
- For Google, each project's redirect allowlist gains the matching frontend
  origin plus the custom scheme. Exact matches, kept tight.
- Session storage is the WebView's `localStorage`, sandboxed per app.
  Acceptable for this phase and consistent with the BYOK key. Moving the
  refresh token to encrypted storage via a Capacitor plugin is a hardening
  follow-up, not a blocker.
- In-app account deletion (above) satisfies Play's policy. The privacy page
  under `app/legal` gains a paragraph on what signing in stores.

## Environments and configuration

| | Railway `dev` | Railway `production` | Local |
|---|---|---|---|
| Supabase project | `videolens-dev` | `videolens-prod` | `videolens-dev`, or none |
| `AUTH_JWKS_URL` / `AUTH_ISSUER` | dev project | prod project | blank, or the dev project |
| `AUTH_AUDIENCE` | `authenticated` | `authenticated` | same |
| `DATABASE_URL` | dev pooler, `videolens_api` | prod pooler, `videolens_api` | blank (in-memory) or `sqlite+aiosqlite:///...` |
| `NEXT_PUBLIC_SUPABASE_URL` / `_PUBLISHABLE_KEY` | dev project | prod project | blank (`NullAuthSession`) or local |
| Supabase redirect allowlist | `https://videolens-frontend-dev.up.railway.app`, custom scheme | prod frontend origin, custom scheme | `http://localhost:3005` (`npm run dev`), `http://localhost:3000` (compose) |

Two cautions from `railway-environments.md`: the frontend variables are
baked into the build, so a value fixed on Railway needs a redeploy; and
forking an environment copies them verbatim, so a fork silently
authenticates against the wrong project until corrected. The four new names
join that doc's "does not survive a fork" list.

Alembic runs as a release step, not at container start: `alembic upgrade
head` against dev after the PR into `dev` merges, against prod after the PR
into `main` merges and before the Railway deploy wakes. Listed in
`DEPLOYMENT.md`.

## Security notes

- Tokens and API keys are never logged. The resolver logs `kid`, `sub` and
  the failure class only.
- API keys are SHA-256 hashed, not slow-hashed: 256 bits of randomness make
  brute force irrelevant and a slow hash only adds latency to every agent
  call.
- Key management and account deletion refuse API keys.
- The verifier is an algorithm allowlist (RS256, ES256); HS256 and `none`
  are refused by construction. `aud` and `iss` are both checked.
- Supabase handles sign-in rate limiting, OTP expiry (set to 10 minutes per
  project) and email enumeration protection. The backend never sees a login.
- The backend holds no Supabase API key, only a Postgres role with minimal
  grants. Nothing on Railway can call the Supabase management or admin REST
  APIs.
- `Authorization` is a credentialed header; `ALLOWED_ORIGINS` stays exact.

## Testing

Backend, mirroring the package layout under `backend/tests/`:

- `infrastructure/auth/test_jwt_verifier.py`: exists on `dev`; add
  expired, wrong `aud`, wrong `iss`, missing `sub`, leeway.
- `application/test_identify_caller.py`: three methods, `vl_live_` routing,
  revoked key, malformed client id, `allow_anonymous` off, `enabled=False`
  directory behaving like today.
- `domain/test_policies.py`: `can_access_run`, `quota_key`.
- `infrastructure/persistence/test_sql_adapters.py`: lifted from the branch
  (SQLite via `aiosqlite`), trimmed to the four tables; add the deleter.
- `interface/api/test_account_routes.py`: 401/403 matrix for `/api/me`,
  `/api/keys`, `DELETE /api/me`.

Frontend: `tsc --noEmit` and `npm run build`; `NullAuthSession` keeps the
build green with blank variables.

Android: CI builds the APK on every PR into `dev`; the owner installs it and
walks the sign-in checklist. Nothing built locally, per `CLAUDE.md`.

## Rollout

Each phase is one PR into `dev`, independently shippable, no behaviour
change for a deployment that leaves the new variables blank.

Phase 0, owner, no code: create `videolens-dev` and `videolens-prod`;
confirm or rotate to an ES256 signing key in both; enable email OTP, set
expiry to 10 minutes, disable magic links; enable the Google provider (one
Google Cloud OAuth client per project); set redirect allowlists; create the
`videolens_api` role and its grants, mint the pooler `DATABASE_URL` per
project (connector); set the Auth settings (dashboard); place backend and
frontend variables on the matching Railway environments.

Phase 0 state on 2026-11-08 (`videolens-dev`, ref `pjekwwiaocywdbwqgtgl`,
`us-east-2`, Postgres 17.11, org `gagan-dev` on Pro): project exists (created
2026-11-07); signing key is ES256 already; `public` was empty. **Done the
same day:** the `videolens_api` login role (no superuser, no bypass-RLS, no
inherit) was created and migration `0001_identity` applied through the
Supabase connector using the offline Alembic render; `alembic_version` is at
`0001_identity`, the four tables have RLS on with the `videolens_api_all`
policy, and the role was verified to log in through the transaction pooler
(`aws-0-us-east-2.pooler.supabase.com:6543`, user
`videolens_api.pjekwwiaocywdbwqgtgl`) and to be refused `auth.users`, as
expected (see `docs/backend/auth.md`, migrations). **Dashboard settings,
also done 2026-11-08** (agent-driven browser, each save confirmed by the
dashboard): Email provider on with *Confirm email* and *Secure email
change* on, OTP expiry 3600 → **600 s** (OTP length 8 digits, dashboard
default); Site URL `https://videolens-frontend-dev.up.railway.app`;
redirect allowlist `https://videolens-frontend-dev.up.railway.app` and
`http://localhost:3005` (`http://localhost:3000` for compose not added yet;
add it when someone needs it). Magic links are off by template, not by a
switch: the *Magic link or OTP* **and** *Confirm sign up* templates (the
latter is what a first-time `signInWithOtp` user receives) now carry
`{{ .Token }}` and no `{{ .ConfirmationURL }}`, subject "Your VideoLens
sign-in code". The project is still on Supabase's built-in SMTP (rate
limited, fine for dev; custom SMTP is a prod-project task). Google provider
waits for phase 4. **Railway `dev` variables set the same day** on the
`videolens-backend` service only, without a redeploy (the deployed `dev`
code ignores unknown settings, so they take effect on the first deploy of
this branch):
`AUTH_JWKS_URL=https://pjekwwiaocywdbwqgtgl.supabase.co/auth/v1/.well-known/jwks.json`,
`AUTH_ISSUER=https://pjekwwiaocywdbwqgtgl.supabase.co/auth/v1`,
`AUTH_AUDIENCE=authenticated`, `DATABASE_URL` (the pooler URL above with the
role password, held outside the repo). Not yet set, frontend:
`NEXT_PUBLIC_SUPABASE_URL=https://pjekwwiaocywdbwqgtgl.supabase.co` and the
`sb_publishable_` key from the dashboard API settings (phase 2). The `auth`
capability on dev `/health` cannot be checked until this branch is merged
into `dev`; `dev` deploys from the `dev` branch, not from feature branches.

Phase 1, backend identity: lift the files listed above onto a branch from
`dev`, with the changes marked. Enable `AUTH_*` and `DATABASE_URL` on
Railway `dev` only. The web app does nothing new yet; verify with a token
copied from the Supabase dashboard and `curl`.

Phase 2, web sign-in: `SupabaseAuthSession`, OTP flow, `AccountPanel`
(signed-out and signed-in basics), bearer on every request, history refetch
on auth change, privacy paragraph. Verified on the `dev` frontend.

Phase 3, API keys and deletion: `/api/keys` UI section, `DELETE /api/me`
and its UI, `database` capability.

Phase 4, Android: Google sign-in via `@capacitor/browser` and the custom
scheme, manifest intent filter, redirect allowlist, verified from the
CI-built APK. OTP needs no Android work and is live from phase 2.

Phase 5, agents: bring `mcp/` from the paid-tier branch onto `dev`
(`VIDEOLENS_API_KEY` alongside the anonymous BYOK mode), and reconcile
`CLAUDE.md`, which currently describes the older `feature/mcp-server` copy.

Then, separately: subscriptions. That work re-adds the `Plan` values,
`Entitlement` numbers, metering, Stripe, the archive and library from the
old branch, and decides what signing in buys at `_admit`. Nothing in phases
1 to 5 needs to change for it.

## Open questions, resolved 2026-11-08

1. Sign-in methods: email code first, Google in phase 4. Apple becomes
   mandatory the day there is an iOS build, not before.
2. Claim anonymous history on sign-in (`POST /api/me/claim`): not in this
   phase. Server-side runs last an hour, so there is little to claim.
3. Supabase region: the Railway region. Confirm the exact region from the
   Railway dashboard before creating the project.
4. Workspaces: keep the table, hidden. It is already written on the old
   branch and saves a migration later.
5. Project count: dev only for now. `videolens-dev` already exists;
   `videolens-prod` waits until billing is close, since nothing in phases 1
   to 3 needs it. The free-tier worry was wrong: the org is on Pro, so a
   third project is a cost question, not a limit.
6. Old branch: tag it `archive/paid-tier-clerk` and delete it after phase 5,
   so the subscription work can still read the billing parts.

## Documents to update when this lands

`docs/backend/auth.md` (becomes the reference for the implemented half;
absorb `accounts-workspaces.md` from the branch), `docs/frontend/
account-panel.md` (from the branch, trimmed), `docs/railway-environments.md`
(fork-unsafe variables), `DEPLOYMENT.md` (the OIDC checklist item, the
Alembic release step), `CLAUDE.md` (Product direction, the lint count, the
`mcp/` paragraph), `docs/engineering-standards.md` (the `mcp/` finding),
`backend/.env.example`, `frontend/.env.example`, `docs/README.md`.

## Changelog

- 2026-11-07 · main session · first draft after the Supabase decision; rewritten the same day once `feat/paid-tier-integration` was found, to lift its identity slice instead of redesigning
- 2026-11-08 · main session · corrected run TTL (1 hour, not 7 days) and the local dev port (3005); noted the `CLAUDE.md` persistence rule; recorded the owner's answers to the six open questions (dev project only for now)
- 2026-11-08 · main session · phase 0 check via the Supabase connector: `videolens-dev` exists, ES256 key confirmed, org on Pro (question 5 reasoning corrected), `auth.users` DELETE not grantable so phase 3 switches to a `SECURITY DEFINER` helper; recorded the Railway variable values
- 2026-11-08 · backend subagent (auth phase 1) · status flipped to phase 1 implemented on `feat/auth-supabase` (pending PR). Deviations: run `owner_id` stays the subject this phase; `/api/me` needs authentication; audience optional; RLS gets a per-role policy; slowapi checks the limit after dependencies, so the limiter reads the resolved principal; distributed without `DATABASE_URL` disables the account store. Details in `backend/auth.md` and the session log
- 2026-11-08 · main session · phase 0 database step done on `videolens-dev`: `videolens_api` role created and `0001_identity` applied through the connector, role login verified via the `aws-0-us-east-2` pooler; Railway variables still to set
- 2026-11-08 · main session · tooling decision: no Supabase CLI (install removed); project administration via the connector, Auth settings via the dashboard; `supabase link` and the local stack dropped from phase 0 and the environment table
- 2026-11-08 · main session · phase 0 finished: dashboard Auth settings set on `videolens-dev` (OTP expiry 600 s, site URL, redirect allowlist, OTP-only templates for magic link and confirm sign up); Railway `dev` backend variables set without redeploy; branch pushed. `/health` check deferred to the merge into `dev`
