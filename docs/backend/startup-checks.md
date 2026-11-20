# Startup checks, schema version, worker lifecycle

What the API and the arq worker check before they serve, how each knows the
database is migrated far enough, and how the worker starts and stops.

## Files

| Layer | File | Role |
|---|---|---|
| domain | `domain/schema_revision.py` | `KNOWN_SCHEMA_REVISIONS` (the Alembic chain, oldest first), `EXPECTED_SCHEMA_REVISION` (its last entry), `SchemaReading`, `SchemaState`, `compare_schema` |
| domain | `domain/ports.py` | `SchemaRevisionReader` port |
| domain | `domain/errors.py` | `SchemaOutOfDateError` (operator-only startup refusal) |
| application | `application/check_schema.py` | `CheckSchemaUseCase`: compare, log, refuse; keeps `last` for readiness |
| infrastructure | `persistence/schema_revision.py` | `SqlSchemaRevisionReader`: reads `alembic_version` through the shared engine |
| infrastructure | `config.py` | `Settings.startup_error(role)`: the configuration rules, one list for both roles |
| interface | `interface/startup.py` | `validate_startup(container, role)`, `mode_fingerprint`, `log_mode` |
| interface | `api/app.py` | lifespan calls `validate_startup(container, API)` |
| interface | `worker/settings.py` | `startup` (JSON logging, then `validate_startup(container, WORKER)`), `shutdown` (`container.close()`), `job_completion_wait` |
| wiring | `container.py` | `check_schema_use_case` (reader only with `DATABASE_URL`; `enforce` off on SQLite), `configure_worker_logging` |

## What runs at startup (both roles, in order)

1. `validate_tools` (ffmpeg/ffprobe) and `validate_temp_dir`.
2. API only: `device_tokens.validate_configuration()`. The device token signs
   and reads free-run cookies, which only the API does (the worker never
   touches `device_tokens`).
3. Worker only: refuses without Redis and object storage.
4. Distributed (`REDIS_URL` set): Redis ping, object storage required, then
   `Settings.startup_error(role)`: the CORS wildcard rule (API only; the
   worker answers no browser), SQLite when distributed, billing configured
   without `DATABASE_URL`. Before 2026-11-20 only the API ran these, so a
   worker could drift silently.
5. The schema check (below). Its query is also the database ping.
6. One log line, `Startup mode {...}`: role, `local`/`distributed`, the
   database dialect or `off`, the schema state, billing, auth and object
   storage on/off. Switches only, never a value, URL or secret. Compare the
   API's line with the worker's after a variable change; a worker with
   `DATABASE_URL` blank while the API has it is not refused (it cannot see
   the API's variables) unless billing is configured, so the two lines are
   how to spot it.

## Schema version check

The image copies only `app/`, so `migrations/` is not there at runtime. The
code carries its own record of the chain in `domain/schema_revision.py`;
`tests/domain/test_schema_revision.py` parses `backend/migrations/versions/`
and fails if `EXPECTED_SCHEMA_REVISION` is not the head or the list is not
the chain in order. **A new migration must add its revision there.**

The reader asks the catalog first, so nothing is classified from error text:
Postgres `to_regclass('alembic_version')`, then
`has_table_privilege('alembic_version', 'SELECT')`, then the row; SQLite
`sqlite_master`. A failed connection is a reading (`reachable=False`), logged
with the exception class only.

| State | Meaning | Postgres | SQLite |
|---|---|---|---|
| `ok` | at `EXPECTED_SCHEMA_REVISION` | starts | starts |
| `behind` | an older known revision | **refuses**, naming found and expected | WARNING, starts |
| `missing` | no `alembic_version` table | **refuses** | WARNING, starts |
| `ahead` | a revision the code does not know | WARNING, starts | WARNING, starts |
| `unreadable` | no SELECT privilege, or no row (RLS without a policy) | ERROR, starts | ERROR, starts |
| `unreachable` | the database did not answer | ERROR, starts | ERROR, starts |
| `disabled` | no `DATABASE_URL` | nothing checked | nothing checked |

Why each choice:

- **Ahead is allowed.** Older code against a newer, additive schema is what a
  rollback looks like; refusing would block the rollback.
- **Unreadable and unreachable start.** The check cannot decide, and
  anonymous use does not need the database; refusing would turn a database
  blip during a deploy into a full outage. The ERROR says the deployment is
  unprotected. On `videolens-dev` the backend role was refused
  `alembic_version` (`auth.md`, "Migrations"), so until the grant in
  `DEPLOYMENT.md` ("Release checklist") is applied the state there will be
  `unreadable`, and **the check protects nothing**: a schema that is in fact
  behind reads as `unreadable` too, and the process starts against it.
- **SQLite only warns.** It is local use only (distributed mode refuses it),
  and tests and some local setups build tables with `Database.create_all()`,
  which writes no `alembic_version`. `alembic upgrade head` on SQLite (the
  documented local path) does write it, and the check then reports `ok`.

`GET /api/readiness` returns the result as `schema` (`capabilities.md`). The
worker reports it in its `Startup mode` line.

**`schema` is a startup snapshot**, not a live reading: it is
`CheckSchemaUseCase.last`, set once when the process started, and readiness
never queries the database (it is the cheap check the platform may poll).
A migration applied while the process runs, or a database that was
`unreachable` at startup and answers now, shows only after a restart. The
live database answer is the `database` row of `/api/capabilities`.

**The worker has no platform health check** (`railway.worker.json` sets none;
the API's is `/api/health`). A worker that refuses (schema behind or
missing, or any other startup refusal) raises from arq's `on_startup`,
before it takes a job, and the process exits; `ON_FAILURE` restarts it up to
3 times and then it stays crashed. Nothing gates the deploy on it, so by
Railway's documented behaviour (not checked here) the refused deployment
still replaces the old worker, and runs wait `queued` until a worker starts
or the run TTL removes them. The refusal is in the worker's log; its absence
of a `Startup mode` line is the tell.

## Database URL

`DATABASE_URL` is checked when the `Database` is built (container
construction, so both roles, before the lifespan or arq startup):
`persistence/database.py` `database_url_error` / `split_tls_connect_args`.
Every query parameter is handed to asyncpg's `connect()`, which takes a
fixed set of keywords, so a libpq-only one (`options`, `application_name`,
`connect_timeout`, `sslcert`, `sslkey`, ...) used to make every connection
fail with a TypeError at the first query. It is now a ValueError at startup
naming the parameters (never their values). `sslmode` is renamed to `ssl`;
an empty one is refused. `sslrootcert` is translated, not passed through:
with `sslmode=verify-full` it becomes an `ssl.SSLContext` trusting only that
CA and checking the host name, with `verify-ca` the same without the host
check, and with any other mode (or a file that cannot be loaded) startup is
refused, since a root certificate without verification would be ignored.
`migrations/env.py` applies the same rules. `sslmode=require` encrypts
without verifying the certificate (DEPLOYMENT.md, "Database connections").

## Logging

`configure_logging()` used to run only in the API. Under `python -m arq`,
arq's dictConfig puts a plain-text handler on the `arq` logger only, so
INFO lines on `videolens` were dropped and errors printed bare. The worker's
`startup` now calls `container.configure_worker_logging()`: the same JSON
root handler, and arq's own handler removed so its lines go through the JSON
handler once instead of twice. Through the container so `interface/worker`
imports nothing from `infrastructure/`.

## Shutdown

`shutdown` calls `container.close()`, which closes every adapter the
container opened, the SQL engine included (it used to close 4 of them and
never dispose the engine). arq calls `on_shutdown` once, from
`Worker.close`.

In-flight jobs on SIGTERM: `WORKER_JOB_COMPLETION_WAIT_SECONDS` (default 0)
and what a cancelled run does are in `job-queue.md` and `run-processing.md`.

## Tests

- `tests/domain/test_schema_revision.py`: constant = migrations head, list =
  chain; `compare_schema` for every state.
- `tests/application/test_check_schema.py`: behind and missing refuse (both
  revisions named), equal ok, ahead warns and continues, unreadable and
  unreachable log an ERROR and continue, SQLite warns, no database skipped.
- `tests/infrastructure/persistence/test_schema_revision_reader.py`: SQLite
  at head and at 0006 through Alembic, `create_all` has no table; the
  Postgres branch with a fake connection (missing, no privilege, RLS, failed
  connection without leaking the error text).
- `tests/interface/test_startup.py`: worker refuses billing without a
  database and SQLite when distributed; CORS and device tokens API-only;
  both roles run the schema check; one mode line with no secrets.
- `tests/interface/worker/test_worker_settings.py`: startup logs `videolens`
  INFO as JSON and arq once; shutdown closes the container once; each job
  passes its own timeout as the deadline; both crons registered, the
  extra-run flush reconciling before reporting and doing nothing with
  billing off, the cleanup cron running its use case.
- `tests/interface/api/test_app_lifespan.py`: the API lifespan runs
  `validate_startup` as the API before serving, a refusal stops the app,
  and the container closes once on shutdown.
- `tests/infrastructure/persistence/test_database_url.py`: `sslmode` renamed;
  unsupported parameters, an empty mode, `sslrootcert` without a verifying
  mode and an unreadable certificate refuse; `verify-full`/`verify-ca` give
  the right `SSLContext` in `connect_args` and nothing reaches asyncpg's
  keywords.
- `tests/infrastructure/persistence/test_schema_migration_drift.py`:
  `schema.py` against the migrated chain on SQLite (Alembic autogenerate
  compare, types and server defaults); four Python-side defaults and the
  Postgres-only foreign-key rewrites (0007, 0009) are the named exceptions.

## Changelog

- 2026-11-20 · Claude (backend agent) · created: one `validate_startup(role)` for the API and the worker, the `alembic_version` check (`EXPECTED_SCHEMA_REVISION`, refuse when behind or missing on Postgres, warn when ahead), the mode line, worker JSON logging and `container.close()` on shutdown
- 2026-11-20 · Claude (backend agent) · tests: API lifespan, worker crons, model-vs-migration drift
- 2026-11-20 · Claude (backend agent) · re-review: readiness `schema` documented as a startup snapshot; the check protects nothing until the grant; the worker has no health check and what a refused worker does; "Database URL": unsupported parameters refuse startup, `sslrootcert` becomes an SSL context with `verify-full`/`verify-ca`
