# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

VideoLens AI: upload short audio/video (or paste a public URL) and get a
transcript, on-screen text extraction, summary, and markdown notes via
Gemini's multimodal video understanding. Backend is FastAPI + arq worker;
frontend is a Next.js PWA with a Capacitor Android wrapper.

- `backend/` — FastAPI API, worker, FFmpeg, Gemini, Redis/S3 adapters
- `frontend/` — Next.js PWA and Capacitor source
- `frontend/android/` — Android API 36 native project
- `mcp/` — MCP server exposing video analysis to terminal AI agents (Claude
  Code, Cursor, Codex, Antigravity); thin REST client over the same
  `backend/` API the frontend uses, not a new backend. See `mcp/README.md`.
- `docs/` — per-feature reference docs (what a feature does, files it
  touches, known issues). Check here before touching a feature; add/update
  the relevant doc when you change one. Doesn't replace this file or the
  `ARCHITECTURE.md` files.

Both backend and frontend have their own `ARCHITECTURE.md` — read those
before making structural changes; they're the authoritative layering
reference and more detailed than the summary below.

## Commands

### Backend (`cd backend`)

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in GEMINI_API_KEY
uvicorn app.main:app --reload

python -m compileall -q app                    # syntax check, run before tests (matches CI)
python -m unittest discover -s tests            # run all tests
python -m unittest tests.application.test_create_run   # run a single test module
python -m unittest tests.application.test_create_run.CreateRunUseCaseTests.test_rejects_missing_terms  # single test
```

Requires `ffmpeg`/`ffprobe` on `PATH`, or `FFMPEG_LOCATION` set — validated
at startup. `backend/tests/` mirrors `backend/app/` (`tests/domain/`,
`tests/application/`, `tests/infrastructure/<adapter>/`,
`tests/interface/api/`); each adapter test constructs the class directly
with an explicit `Settings(...)` rather than monkeypatching a module-level
global.

### Frontend (`cd frontend`)

```bash
npm install
cp .env.example .env.local
npm run dev              # dev server
npx tsc --noEmit         # typecheck (CI uses this, no separate test suite)
npm run build             # production build
npm run build:mobile      # Capacitor build (sets CAPACITOR_BUILD=true)
npm run lint
```

### Android (`cd frontend`)

```bash
npm run android:sync      # build:mobile + cap sync android
cd android && ./gradlew assembleDebug testDebugUnitTest
```

`frontend/android/app/build.gradle` reads `versionName` from
`frontend/package.json`'s `version` — bump it there for releases.
`versionCode` is supplied at build time (CI passes the GitHub Actions run
number); local builds default to `1`. `frontend/android/debug.keystore` is
checked into the repo intentionally (not a secret) so every debug build —
local or CI — signs with the same identity, letting a freshly downloaded
APK install as an update over an existing one.

### MCP server (`cd mcp`)

```bash
npm install
npm run build             # emits dist/index.js
GEMINI_API_KEY=... node dist/index.js   # manual smoke test; real usage is via an MCP client, not direct invocation
```

Not published to npm yet — see `mcp/README.md` for how agents (Claude Code,
Cursor, etc.) point at the local build in the meantime, and the repo's own
root `.mcp.json` for the config this repo's contributors get automatically.

### Docker Compose (full stack)

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

Frontend at `:3000`, backend at `:8000`, MinIO console at `:9001`.

### CI (`.github/workflows/ci.yml`)

Three jobs: `backend` (compileall + unittest discover + import check),
`frontend` (tsc + build + build:mobile), `android` (gradle assemble +
test, uploads APK artifact, publishes a GitHub Release on push to `dev`).

## Architecture

Both backend and frontend follow the same clean-architecture layering,
dependencies pointing inward toward `domain/`:

```
domain  <-  application  <-  infrastructure
                           <-  interface (api, worker / app+components)
```

`infrastructure/` and `interface/` never import each other directly — only
`container.py` (backend) / `infrastructure/container.ts` (frontend) wires
them together.

### Backend (`backend/app/`)

- **`domain/`** — pure types/rules, no I/O: `entities.py` (`Run`,
  `VideoAnalysis`, `Principal`, ...), `errors.py`, `policies.py`,
  `ports.py` (structural `Protocol` interfaces adapters satisfy by
  duck-typing, no inheritance needed: `RunRepository`, `MediaProcessor`,
  `AnalysisEngine`, `ObjectStore`, `JobQueue`, `SpendCap`, `KeyVault`,
  `TokenVerifier`).
- **`application/`** — one use case per user-facing operation, orchestrating
  ports: `create_run.py`, `get_run.py`, `list_runs.py`, `process_run.py`
  (the download → normalize → analyze → persist pipeline, run identically
  by the in-process local runner and the arq worker).
- **`infrastructure/`** — concrete adapters, each taking `Settings` in its
  constructor (not a module-level global) for independent testability:
  `persistence/run_repository.py` (Redis or in-process dict),
  `media/service.py` (composes ffmpeg + yt-dlp + uploads into one
  `MediaProcessor`), `ai/gemini_engine.py`, `storage/s3_object_store.py`,
  `queue/job_queue.py` (arq/Redis or in-process asyncio task),
  `quota/daily_budget.py`, `byok/key_vault.py`, `auth/jwt_verifier.py`.
- **`interface/`** — the only layer allowed to know FastAPI/arq directly:
  `api/app.py` (app factory, lifespan, CORS, rate-limit middleware),
  `api/routes.py` (thin handlers — extract request, call one use case via
  `container`, return a schema), `api/schemas.py` (response DTOs,
  deliberately not merged with `domain.entities.Run` so `owner_id` never
  leaks), `api/dependencies.py` (`get_principal`), `api/error_handlers.py`
  (domain exception → HTTP status), `worker/settings.py` (arq
  `WorkerSettings`).
- **`container.py`** — composition root; builds every adapter once, wires
  use cases. Only file allowed to import from every layer.
  `app/main.py`/`app/worker.py` are one-line re-export shims so
  `Dockerfile`/`docker-compose.yml`/`railway.worker.json` (which reference
  `app.main:app` / `app.worker.WorkerSettings`) needed no changes.

Adding something new: new business rule → edit the `application/` use case
(it only sees ports). New storage backend / swap the model → new
`infrastructure/` adapter satisfying the matching `domain.ports` Protocol,
point `container.py` at it. New endpoint → route in
`interface/api/routes.py` calling a use case.

### Frontend (`frontend/`)

Same layering, lighter — no per-adapter DI ceremony beyond
`infrastructure/container.ts`, which builds the one shared instance of each
adapter every hook imports from (e.g. one `ApiKeyStore` backing both
`useGeminiApiKey` and `FetchRunsGateway`'s headers).

- **`domain/`** — pure types, no `fetch`/`localStorage`/React:
  `entities.ts`, `errors.ts`, `ports.ts` (`RunsGateway`, `ApiKeyStore`,
  `VersionLogGateway`, `UpdateChecker`).
- **`infrastructure/`** — one adapter per external system:
  `runsGateway.ts` (`FetchRunsGateway`, builds `X-Client-ID`/
  `X-Gemini-Api-Key` headers), `apiKeyStore.ts` (`LocalStorageApiKeyStore`),
  `versionLogGateway.ts` (`GithubVersionLogGateway`), `updateCheck.ts`
  (`GithubUpdateChecker`, native-Android-only via `@capacitor/app`),
  `container.ts`.
- **`application/`** — one hook per state/orchestration concern:
  `useAnalysisRun.ts` (core state machine: submit/poll/open-from-history/
  reset), `useGeminiApiKey.ts`, `useRunHistory.ts`, `useVersionLog.ts`,
  `useUpdateCheck.ts`. Components never call an adapter directly.
- **`app/` + `components/`** — framework-bound presentation. `app/` holds
  only what Next.js requires (route files, global CSS); `app/page.tsx` is
  4 lines rendering `<HomeScreen />`. `components/HomeScreen.tsx` is the
  real page body (header, tabs, composes `useAnalysisRun()` with
  presentational pieces); `components/panels/{ApiKeyPanel,HistoryPanel,
  VersionLogPanel}.tsx` are one-per-tab; `format.ts` holds the shared
  `formatDate`.

Adding something new: new client state/API call → hook in `application/`,
port in `domain/ports.ts` if it talks externally, adapter in
`infrastructure/`, registered in `container.ts`. New tab/panel → component
in `components/panels/`, wired into `HomeScreen.tsx`'s tab list.

## How a run flows

1. Frontend `POST /api/runs` (multipart: `file` XOR `url`) → `202` with
   `{ run_id, status: "queued" }` after validating an uploaded file.
   Requires `X-Client-ID` (scopes visible runs, not quota) and
   `accept_terms=true`.
2. For URL runs, backend downloads via yt-dlp first. Either way: validate +
   normalize with FFmpeg → upload to Gemini → analyze.
3. Frontend polls `GET /api/runs/{run_id}` until `status` is `complete` or
   `failed`; `stage` (only set while `processing`) is one of
   `downloading`, `normalizing`, `uploading_to_gemini`, `analyzing`.
4. `GET /api/runs` returns the caller's own history (newest first, capped
   at 20), owner-bound and Redis-expired after `RUN_TTL_SECONDS`.

Local dev can run entirely in-process (no Redis/arq); production mode uses
Redis + arq worker + S3-compatible storage. Uploaded/downloaded files are
deleted after every run, success or failure.

### Bring-your-own-key (BYOK)

The in-app menu's API key panel lets a user paste their own Gemini key,
stored only in browser `localStorage`, sent as `X-Gemini-Api-Key`. Backend
never writes it to `RunStore` or logs it. In distributed mode it can't
travel as a normal arq job argument (arq logs job args), so it's held in a
single-use Redis entry (`infrastructure/byok/key_vault.py`) keyed by
`run_id`, deleted the instant the worker reads it, with a 15-minute
safety-net TTL. BYOK runs are exempt from `DAILY_RUN_CAP` but still subject
to the normal per-IP rate limit.

### MCP server (`mcp/`)

Lets terminal AI agents (Claude Code, Cursor, Codex, Antigravity, ...) call
VideoLens directly via two tools: `analyze_video` (blocks until the run
finishes, returns the parsed result) and `list_recent_runs`. It's a thin
Node/TypeScript REST client over the same `POST /api/runs` /
`GET /api/runs{,/{run_id}}` endpoints the frontend uses — no new backend
surface, no shared use-case code (matches `frontend/infrastructure/
runsGateway.ts`'s role, different transport).

Two things deliberately differ from the web app's BYOK panel:

- **BYOK is mandatory, not optional.** Agent-driven traffic can loop or
  batch far more easily than a human clicking upload, so there's no
  shared-quota fallback — every call requires the caller's own
  `GEMINI_API_KEY`, supplied only via the MCP client's `env` config (never
  a tool argument, never a file on disk — read once from `process.env` at
  process start, mirroring how every major MCP server handles credentials).
- **Client identity is a local dotfile, not `localStorage`.** `~/.videolens/
  client_id` (`mcp/src/clientId.ts`) is created once and reused, playing the
  same non-secret scoping role `X-Client-ID` plays for the web app — it
  only determines what `list_recent_runs` can see, never authorizes quota.

### Cost protection

No accounts, no paid tier — server-side limits are the only thing gating
Gemini spend. Two independent caps: `RATE_LIMIT_PER_HOUR` (per-IP or
per-token, Redis-backed across replicas when `REDIS_URL` is set) and
`DAILY_RUN_CAP` (global backstop across all callers, UTC day). Both are
checked before any download/FFmpeg work happens. `ALLOWED_ORIGINS` must
never be `*` in production — the backend logs a startup warning if it
detects a distributed deployment still running with `*`.

## Configuration

See `backend/.env.example` and `frontend/.env.example`. Key backend
settings: `GEMINI_API_KEY`, `GEMINI_MODEL`, `MAX_FILE_SIZE_MB`,
`MAX_DURATION_SECONDS`, `RATE_LIMIT_PER_HOUR`, `DAILY_RUN_CAP`,
`RUN_TTL_SECONDS`, `FFMPEG_LOCATION`, `REDIS_URL`, `S3_*`, optional
`AUTH_*` OIDC settings, `ALLOWED_ORIGINS`. Login-gated URL sources (some
Instagram links etc.) need either `YTDLP_COOKIES_FROM_BROWSER` (local) or
`YTDLP_COOKIES_FILE` pointing at a mounted Netscape-format cookie file
(deployed) — configure only one, and never commit a cookie file.

## Product direction

**Right now**: stay free, open-source-ready, and usable both logged-in and
anonymous, from desktop or mobile, and callable by any AI agent/terminal
tool (Claude Code, Cursor, Codex, Antigravity, etc. — not just the web/PWA
UI). Don't add accounts, billing, or server-side-persistent-by-default
storage yet — that would conflict with "usable anonymously" and complicate
the pre-open-source cleanup. Client-side storage (BYOK key, and any run
history moved client-side) fits this phase; keep it that way for now.

**Later (explicitly deferred, not scoped yet)**: a paid tier is planned,
opt-in, after the open-source publish. When that's picked up, it needs real
auth (the currently-unused `AUTH_*` OIDC settings) and durable server-side
storage keyed by real user ID instead of the spoofable `X-Client-ID` —
likely Postgres for paid-user history, since Redis's `RUN_TTL_SECONDS`
expiry and lack of durability guarantees make it unsuitable as a system of
record for billed users. Free/anonymous usage stays client-side-only even
after this ships.

## Deployment

Railway: `backend/railway.json` (API), `backend/railway.worker.json`
(worker, same image/vars as API), `frontend/railway.json`. Point the
frontend's `NEXT_PUBLIC_API_BASE_URL` at the deployed backend and set
backend `ALLOWED_ORIGINS` to the deployed frontend origin. See
`DEPLOYMENT.md` for what's still required before public release (OIDC
provider choice, production domains/secrets, Android signing key, Play
Console setup).

## Operating rules for Railway / infra tools

These exist because both were violated in a real session (2026-08-14) and
caused real problems — treat them as binding, not suggestions.

- **Never call a tool that bulk-dumps secrets** (e.g. Railway MCP's
  `list_variables`, which returns every `KEY=VALUE` on a service including
  API keys, DB passwords, S3 credentials) just to check one field's state.
  Prefer a scoped check, or ask the user to confirm from the dashboard. If
  no scoped option exists and a full dump is unavoidable, say so and get
  confirmation *before* calling it, not after — a "don't paste secrets"
  warning after the fact doesn't undo a dump already in the transcript.
- **Don't assert unverified infra/integration state as confirmed fact.** A
  config field (e.g. a service's `Source repo` value) reflects what's
  *configured*, not whether it actually works end-to-end (e.g. whether the
  GitHub App install behind it is authorized). If the check was shallow,
  say so or ask the user to confirm from the dashboard, rather than saying
  "confirmed" / "verified live."
- Config/IaC changes touching Railway (service settings, variables,
  reconnecting sources) are the kind of action that needs a heads-up before
  acting per this repo's general risk posture — doubly true here since
  services span both `videolens` and other unrelated projects sharing the
  same account/GitHub App installation.
