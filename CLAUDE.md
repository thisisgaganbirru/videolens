# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

VideoLens AI: upload short audio/video (or paste a public URL) and get a
transcript, on-screen text extraction, summary, and markdown notes via
Gemini's multimodal video understanding. Backend is FastAPI + arq worker;
frontend is a Next.js PWA with a Capacitor Android wrapper. Version
`2.2.0` as of 2026-11-06 (`frontend/package.json` is the single source of
truth for the version string).

- `backend/` — FastAPI API, worker, FFmpeg, Gemini, Redis/S3 adapters
- `frontend/` — Next.js PWA and Capacitor source
- `frontend/android/` — Android API 36 native project (plus three small
  Java plugins the app module owns: `NativeThemePlugin`, `FontScalePlugin`,
  `FontScaleScript`)
- `docs/` — per-feature reference docs (what a feature does, files it
  touches, known issues). Check here before touching a feature; add/update
  the relevant doc when you change one. Doesn't replace this file or the
  `ARCHITECTURE.md` files. `docs/README.md` indexes every doc.
- `scripts/workspace.ps1` — the Docker Compose local-workspace lifecycle
  (`check`/`up`/`verify`/`test`/`scan`/`down`); PowerShell, the owner's
  machine is Windows.
- `.github/` — the CI lanes (see "CI" below) and Dependabot config.
- `mem/` — per-task session logs (`mem/YYYYMMDD-{slug}.md`: The Ask, Changes
  Made, Decisions & Rationale, Current Architecture). Gitignored, local only.
  Search here before re-deriving why something was built a certain way.

**Not on this branch, deliberately:** `mcp/` (the MCP server for terminal AI
agents) and the root `.mcp.json` live only on the unmerged branch
`feature/mcp-server` (last commit 2026-08-13). They are parked until the
frontend is settled and will be merged later. Do not treat their absence as a
bug, and do not delete the MCP sections below; they describe that branch.
`docs/engineering-standards.md` records the decision. Other parked branches:
`feat/paid-tier-integration` (2026-10-04, the deferred paid tier) and
`claude/electron-app-uzybrk` (2026-08-16).

**This applies to every agent and subagent, with no exceptions.** If you were
dispatched to do a piece of work — however small — you read the relevant doc
under `docs/` before starting, and you update it plus the `mem/` entry before
reporting back. The agent that did the work is the one that knows what changed
and why; deferring it to whoever dispatched you loses that. Append a one-line
entry to the doc's `## Changelog` naming yourself (`YYYY-MM-DD · <who> ·
<what>`) so parallel agents sharing these files can see what has already been
done instead of duplicating or reverting it. See `docs/README.md`.

Both backend and frontend have their own `ARCHITECTURE.md` — read those
before making structural changes; they're the authoritative layering
reference and more detailed than the summary below.

## Commands

### Backend (`cd backend`)

```bash
pip install -r requirements.txt       # hash-locked; regenerate from requirements.in with uv (see below)
cp .env.example .env                  # fill in GEMINI_API_KEY
uvicorn app.main:app --reload

python -m compileall -q app                    # syntax check, run before tests (matches CI)
python -m unittest discover -s tests            # run all tests (398 as of 2026-11-07, ~7s)
python -m unittest tests.application.test_create_run   # run a single test module
python -m unittest tests.application.test_create_run.CreateRunUseCaseTests.test_rejects_missing_terms  # single test
GEMINI_API_KEY=ci-test-key python -c "import app.main; import app.worker"   # import check (CI runs this too)
```

Python `3.13` (`/.python-version`). Requires `ffmpeg`/`ffprobe` on `PATH`, or
`FFMPEG_LOCATION` set — validated at startup. `backend/tests/` mirrors
`backend/app/` (`tests/domain/`, `tests/application/` with shared fakes in
`tests/application/fakes.py`, `tests/infrastructure/<adapter>/`,
`tests/interface/api/`); each adapter test constructs the class directly with
an explicit `Settings(...)` rather than monkeypatching a module-level global.

`backend/requirements.txt` is a **universal, hash-locked** compile of
`requirements.in`. Regenerate it only with

```bash
uv pip compile requirements.in --generate-hashes --python-version 3.13 --universal --output-file requirements.txt
```

A plain `pip-compile` resolves for the runner's own platform and silently
drops the PEP 508 environment markers (`uvloop` is Linux/macOS only); CI
fails the backend job if the `uvloop` marker is missing, because Dependabot
PR #95 did exactly that and broke `pip install` on Windows. There is no
`pyproject.toml`, `ruff`, or `mypy` yet (see `docs/engineering-standards.md`).

### Frontend (`cd frontend`)

```bash
npm install                # or npm ci, which is what CI and the Dockerfile do
cp .env.example .env.local
npm run dev                # dev server on http://localhost:3005 (allowed by the backend's default ALLOWED_ORIGINS)
npx tsc --noEmit           # typecheck (CI uses this, no separate test suite)
npm run build              # production build (standalone) + generates public/sw.js
npm run build:mobile       # Capacitor build: output "export" + fix-export-segments + sw for out/
npm run lint
```

Node `24` (`/.nvmrc`). Next 16, React 19, Tailwind 3 (v4 is a planned
migration, Dependabot ignores the major), Capacitor 8.

`next.config.mjs` sets **`agentRules: false`** deliberately — leave it off.
Without it, every `next dev` writes `frontend/AGENTS.md` and
`frontend/CLAUDE.md`. The second one is the problem: a subdirectory `CLAUDE.md`
is auto-loaded as agent context whenever someone works in `frontend/`, making it
a competing instruction source alongside this file. Next emits both files
together, so disabling generation is the only way to suppress just that one.
Agent instructions for this repo live here, in the root `CLAUDE.md`, only.

`frontend/public/sw.js` is **generated** by `scripts/build-sw.mjs` from
`sw/sw.template.js` after every build (it carries the build's content-hashed
chunk names) and is gitignored. Edit the template, never the output.
`scripts/fix-export-segments.mjs` repairs the static export's per-segment RSC
file paths, which Next 16.4 writes wrongly on Windows.

`npm run lint` **works again** as of 2026-08-29. It was broken for a long
while — Next 16 removed `next lint`, so the script resolved `lint` as a
directory (`no such directory: frontend/lint`) — and was repaired by running
`npx @next/codemod@latest next-lint-to-eslint-cli`, which rewrote the script to
`eslint .`, added `eslint` + `eslint-config-next` as devDependencies, and
created `frontend/eslint.config.mjs`.

Two things about that config are hand-written and load-bearing:

- **`android/**` is ignored.** The codemod's default ignores miss it, and the
  Capacitor native project holds 80 `.js` files — Gradle intermediates plus the
  web bundle `cap sync` copies into `app/src/main/assets/public/`. None of it is
  hand-written. Without the ignore, `eslint .` reports ~8,940 problems, of which
  7 are in code anyone here writes. `public/sw.js` is ignored for the same
  reason (generated from `sw/sw.template.js` on every build, and gitignored).
- **`@next/next/no-html-link-for-pages` is off for `app/offline/**` only.** That
  page is served from the service-worker cache with the network down, where a
  client-side RSC navigation cannot resolve, so its links are plain `<a>` on
  purpose — see `docs/frontend/legal-offline-routes.md`. The rule stays on
  everywhere else.

`npm run lint` currently **exits 1** with 4 errors and 1 warning (re-verified
2026-11-07), all pre-existing: `react-hooks/set-state-in-effect` in
`useGeminiApiKey.ts` and `UploadForm.tsx` (×2), and one
`@next/next/no-img-element` warning (`ResultsView.tsx`). They are the
read-`localStorage`-after-hydration pattern this app needs to avoid a
hydration mismatch on a static export; they were deliberately **not** "fixed",
because silencing the rule or rewriting the effects is a behavioural decision
for the owner, not lint tidying. CI still does not run it (the frontend job is
`tsc --noEmit` + `build` + `build:mobile`), so this is not gating anything today.

### Android (`cd frontend`)

```bash
npm run android:sync      # build:mobile + cap sync android
cd android && ./gradlew assembleDebug testDebugUnitTest
```

`frontend/android/app/build.gradle` reads `versionName` from
`frontend/package.json`'s `version` — bump it there for releases.
`versionCode` is supplied at build time (`-PappVersionCode`; CI passes
`git rev-list --count HEAD`); local builds default to `1`.
`frontend/android/debug.keystore` is checked into the repo intentionally (not
a secret) so every debug build — local or CI — signs with the same identity,
letting a freshly downloaded APK install as an update over an existing one.

**Where APKs come from.** Three places, each for a different purpose:

- **Production**: every push to `main` builds the APK against the production
  backend and publishes it to GitHub Releases. That is the only APK anyone
  installs for real, and the only one the in-app update check offers.
- **Dev / testing**: every PR into `dev` that touches `frontend/` builds the
  APK against the dev backend (`videolens-backend-dev.up.railway.app`) and
  keeps it as a workflow artifact for 14 days (`videolens-ai-dev-v<version>-
  code<code>-<sha>`), downloadable from the run page. It is built with
  `-PdevBuild=true`, which gives it the `.dev` application id suffix and a
  `-dev` version name, so it installs beside the production app rather than
  over it. Never a release.
- **Local**: `npm run android:sync`, `cap sync android` and
  `./gradlew assembleDebug testDebugUnitTest` are allowed on a developer
  machine for previews and device QA. QA tests the bundled APK on a device or
  emulator, never live reload against the dev server. A local APK is never
  shipped or attached anywhere.

**In a cloud session, do not run the mobile build.** There is no device to
install on, so a Gradle build there only burns minutes on an APK that is
thrown away; push the change and read the dev lane's Android job instead. If
something genuinely cannot be checked any other way, stop and ask the owner.

This does **not** restrict the web build — `npm run build`, `npx tsc
--noEmit`, and `npm run dev` are all fine and are how frontend work gets
verified.

### MCP server (`cd mcp`, on branch `feature/mcp-server` only)

```bash
npm install
npm run build             # emits dist/index.js
GEMINI_API_KEY=... node dist/index.js   # manual smoke test; real usage is via an MCP client, not direct invocation
```

Not on `dev`/`main` and not published to npm; `mcp/README.md` on that branch
covers how agents (Claude Code, Cursor, etc.) point at the local build.

### Docker Compose (full stack)

```bash
cp backend/.env.example backend/.env
docker compose up --build          # or, on Windows: .\scripts\workspace.ps1 up
```

Frontend at `:3000`, backend at `:8000`, MinIO console at `:9001`, all bound
to `127.0.0.1`. Setting `REDIS_URL` makes this stack "distributed", so the
compose file supplies a local-only `DEVICE_TOKEN_SECRET` placeholder. The
compose file is the local workspace only; it is never a deployment manifest.
Full reference: `docs/container-workflows.md`, "Local workspace".

### CI (`.github/workflows/`)

Three independent lanes in a caller/reusable split, redesigned 2026-10-29 so
each check runs **once**, where it decides something. Callers decide when;
reusables hold the steps; composite actions in `.github/actions/`
(`setup-backend`, `setup-frontend`, `setup-android`) hold the setup every job
repeats and read the runtime majors from `/.python-version` and `/.nvmrc`.

| Trigger | Runs |
|---|---|
| PR into `dev` | only what the PR touches (path-classified): backend and/or frontend checks, Android if `frontend/` changed (dev APK kept as a 14-day artifact), **advisory** security scan, `lint-workflows` (actionlint + shellcheck) if `.github/` changed |
| push to `dev` | nothing; the PR tested this tree. Railway deploys |
| PR into `main` | full application checks, **enforced** security scan |
| push to `main` | build each image once, scan it (enforced), promote to `latest`; Android APK; release |
| nightly (06:17 UTC) | advisory scan of `main`; opens/closes a tracking issue |

The backend job also fails if `backend/Dockerfile`'s `FROM python:` major
disagrees with `/.python-version`, or if `requirements.txt` lost its
environment markers; the frontend job fails if `frontend/Dockerfile`'s
`FROM node:` major disagrees with `/.nvmrc`. Dependabot targets `dev` (never
`main`), groups minor/patch bumps weekly per ecosystem, and ignores runtime
majors (Node, Python, Tailwind).

**Security is mandatory for production only.** Advisory runs must finish
**green** (findings go to a warning, the job summary and an artifact): Railway's
Wait for CI skips a deploy while any workflow on the commit is red, so a red
advisory or nightly run would silently block a deploy.

**Branch protection requires the `required` job**, which each caller ends with
and which always reports, never the individual jobs (the `dev` lane skips
jobs on purpose). It also relies on "require branches to be up to date before
merging" and no direct pushes to `dev`/`main`; these are repository settings,
not files, and have been in place since 2026-11-06.

**Releases are published from `main` only**, and the release job waits on the
security-gated publish. `dev` builds the APK as a gate and keeps it as a
short-lived testing artifact with the `.dev` application id; it is never
released.

The reusables: `reusable-application-checks.yml` (backend compileall +
unittest discover + import check; frontend `tsc --noEmit` + `build` +
`build:mobile`; `backend`/`frontend` inputs), `reusable-android-checks.yml`
(gradle `assembleDebug` + `testDebugUnitTest`; `upload_apk` for the release
build, `dev_artifact` for the dev APK, `api_base_url` baked in as
`NEXT_PUBLIC_API_BASE_URL`), `reusable-security-scan.yml` (Dockerfile lint,
image build, Grype; `enforce` input), `reusable-container-publish.yml`
(multi-arch push to GHCR under `sha-<commit>`, scan of that digest,
`imagetools` promotion to `latest`, in-registry SBOM and provenance; the
frontend's backend URL comes from `vars.PRODUCTION_API_BASE_URL` on the
`production` GitHub environment).

Images are deliberately **not** signed. Cosign's keyless mode was removed
because it writes a permanent, undeletable entry to Rekor, the public
transparency log — and keyless signatures cannot be kept without it, since
the short-lived certificate is only verifiable through that log. The SBOM and
provenance attestations stay: BuildKit attaches those to the image index in
the destination registry, so they never leave it. Because `provenance:
mode=max` records build arguments, never pass a secret via `build-args` —
use the `secrets` input.

Three properties worth preserving if you touch these:

- **Exactly one job in the whole set has `contents: write`** — the release
  job in `production-environment.yml`. Everything else is `contents: read`.
  The Android build steps live in a reusable precisely so the `dev` PR gate
  and the `main` release build run the same steps without either holding a
  write token. (The nightly scan's issue job has `issues: write`, nothing more.)
- **`target_commitish: ${{ github.sha }}` on the release step is
  load-bearing.** It pins the tag to the commit the APK was built from rather
  than to wherever the branch tip has moved. This shipped broken once, back
  when releases ran on `dev` and the tag landed on `main`; don't drop it.
- **`versionCode` is `git rev-list --count HEAD`, not `github.run_number`.**
  It must never decrease: Android refuses to install an APK below the
  installed code, and `updateCheck.ts` compares these to find a newer build.
  `run_number` is per-workflow and resets to near zero whenever a different
  workflow starts publishing — which is precisely what moving releases from
  `dev` to `main` did. This also means the Android checkout needs
  `fetch-depth: 0`; at the default depth of 1 every build is version 1.

Full reference — trigger table, tag scheme, signing, the container channels,
runtime-version policy — is `docs/container-workflows.md`. Read it before
editing a workflow. `docs/railway-environments.md` covers how a green run
turns into a deploy, and the three ways a deploy silently does not happen.

## Architecture

Both backend and frontend follow the same clean-architecture layering,
dependencies pointing inward toward `domain/`:

```
domain  <-  application  <-  infrastructure
                           <-  interface (api, worker / app+components)
```

`infrastructure/` and `interface/` never import each other directly — only
`container.py` (backend) / `infrastructure/container.ts` (frontend) wires
them together. (`docs/engineering-standards.md` lists the three known backend
exceptions to that rule; nothing enforces it mechanically yet.)

### Backend (`backend/app/`)

- **`domain/`** — pure types/rules, no I/O: `entities.py` (`Run`,
  `VideoAnalysis`, `AnalysisCompleteness`, `SourceMetadata`, `CaptionTrack`,
  `MediaVisuals`, `Capability`/`CapabilityReport`, `ReleaseIndex`,
  `FreeRunStatus`/`FreeRunClaim`, `Principal`, ...), `errors.py`
  (`UserFacingError` and its subclasses carry a phone-readable message plus an
  operator-only `log_detail`), `policies.py` (`quota_key_from_headers`,
  `is_valid_client_id`, `is_run_stale`), `run_facts.py` (the media facts a
  history card shows, derived from a stored run), `ports.py` (structural
  `Protocol` interfaces adapters satisfy by duck-typing, no inheritance
  needed: `RunRepository`, `MediaProcessor`, `SourceResolver`,
  `AnalysisEngine`, `ObjectStore`, `JobQueue`, `SpendCap`,
  `DeviceTokenSigner`, `FreeRunAllowance`, `KeyVault`, `TokenVerifier`,
  `CapabilityProbe`, `ReleaseCatalog`).
- **`application/`** — one use case per user-facing operation, orchestrating
  ports: `create_run.py` (validation, admission — BYOK or a free run against
  a signed device token — daily budget, save/enqueue, cleanup and refund on
  partial failure), `get_run.py` (ownership check plus the abandoned-run
  backstop: a `queued`/`processing` run untouched for longer than
  `WORKER_JOB_TIMEOUT_SECONDS + 120` is reported and persisted as failed),
  `list_runs.py`, `get_free_runs.py`, `get_capabilities.py` (runs the probes,
  cached a few seconds), `get_releases.py` (cached, serves the last good
  answer on failure), `process_run.py` (the download → normalize → analyze →
  persist pipeline, with the caption-only fallback, run identically by the
  in-process local runner and the arq worker).
- **`infrastructure/`** — concrete adapters, each taking `Settings` in its
  constructor (not a module-level global) for independent testability:
  `persistence/run_repository.py` (Redis or in-process dict),
  `media/service.py` (composes ffmpeg + the resolver chain + uploads +
  thumbnails + captions into one `MediaProcessor`; `media/resolvers/` is an
  ordered chain, yt-dlp first then a stdlib direct-HTTP fetch for links that
  name a media file outright; `media/net.py` is the single SSRF guard every
  outbound fetch goes through; `media/captions.py` is the subtitle salvage
  path), `ai/gemini_engine.py` (plus `ai/source_context.py`, which fences
  publisher metadata off as untrusted text in the prompt),
  `storage/s3_object_store.py`, `queue/job_queue.py` (arq/Redis or an
  in-process asyncio task), `quota/{daily_budget,device_tokens,
  free_run_allowance}.py`, `byok/key_vault.py`, `auth/jwt_verifier.py`,
  `health/probes.py` (one probe per dependency, exercised where cheap),
  `releases/github_releases.py`, `config.py`, `logging_config.py`.
- **`interface/`** — the only layer allowed to know FastAPI/arq directly:
  `api/app.py` (app factory, lifespan, CORS, rate-limit middleware),
  `api/routes.py` (thin handlers — extract request, call one use case via
  `container`, return a schema), `api/schemas.py` (response DTOs,
  deliberately not merged with `domain.entities.Run` so `owner_id` never
  leaks), `api/dependencies.py` (`get_principal`), `api/error_handlers.py`
  (domain exception → HTTP status, `Retry-After` on the 429/503s),
  `api/rate_limiter.py` (slowapi; the one import-time global, see
  `docs/engineering-standards.md`), `worker/settings.py` (arq
  `WorkerSettings`; takes the BYOK key out of the vault before running the
  use case).
- **`container.py`** — composition root; builds every adapter once, wires
  use cases, orders the resolver chain and the capability probes. Only file
  allowed to import from every layer. `app/main.py`/`app/worker.py` are
  one-line re-export shims so `Dockerfile`/`docker-compose.yml`/
  `railway.worker.json` (which reference `app.main:app` /
  `app.worker.WorkerSettings`) needed no changes.

Adding something new: new business rule → edit the `application/` use case
(it only sees ports). New storage backend / swap the model → new
`infrastructure/` adapter satisfying the matching `domain.ports` Protocol,
point `container.py` at it. New URL source → a `SourceResolver` in
`media/resolvers/`, added to the chain in `MediaService`. New endpoint →
route in `interface/api/routes.py` calling a use case.

### Frontend (`frontend/`)

Same layering, lighter — no per-adapter DI ceremony beyond
`infrastructure/container.ts`, which builds the one shared instance of each
adapter every hook imports from (e.g. one `ApiKeyStore` backing both
`useGeminiApiKey` and `FetchRunsGateway`'s headers).

- **`domain/`** — pure types, no `fetch`/`localStorage`/React:
  `entities.ts`, `errors.ts` (`ApiError` with `status`/`code`/`limit`/`used`,
  `NetworkError`, `StorageUnavailableError`), `platforms.ts` (platform names
  and host → platform), `ports.ts` (`RunsGateway`, `HistoryStore`,
  `CapabilitiesGateway`, `ActiveRunStore`, `ApiKeyStore`, `DeviceTokenStore`,
  `FreeRunsGateway`, `VersionLogGateway`, `UpdateChecker`,
  `UpdateDismissalStore`, `SharedUrlSource`, `SystemBarsStyler`,
  `NativeThemeMirror`, `FirstRunStore`, `NativeShell`, `DocumentExporter`).
- **`infrastructure/`** — one adapter per external system, all registered in
  `container.ts`: `runsGateway.ts` (`FetchRunsGateway`, builds `X-Client-ID`/
  `X-Gemini-Api-Key`/`X-Device-Token` headers), `apiBase.ts` (the one
  `NEXT_PUBLIC_API_BASE_URL` fallback), `capabilitiesGateway.ts`,
  `freeRunsGateway.ts` + `deviceTokenStore.ts` + `clientId.ts`,
  `historyStore.ts` (`IndexedDbHistoryStore`), `activeRunStore.ts`
  (sessionStorage, so a reload resumes the run being watched),
  `apiKeyStore.ts` (`LocalStorageApiKeyStore`), `versionLogGateway.ts`,
  `updateCheck.ts` (`ApiUpdateChecker`, native-Android-only via
  `@capacitor/app`, asks `GET /api/releases`), `updateDismissalStore.ts`,
  `sharedUrlSource.ts`, `firstRunStore.ts`, and the Capacitor-only shells:
  `nativeShell.ts` (hardware back, resume, exit), `systemBars.ts`,
  `nativeTheme.ts` (the app's own `NativeTheme` plugin), `documentExporter.ts`
  (share/save a result; on Android writes a real `.md` and opens the share
  sheet with the file).
- **`application/`** — one hook or React-free module per state/orchestration
  concern: `useAnalysisRun.ts` (core state machine: submit/poll/open-from-
  history/reset), `historySync.ts` (History writes), `useRunHistory.ts`,
  `useFreeRuns.ts`, `useCapabilities.ts`, `serverReachability.ts`,
  `gatewayError.ts`, `useGeminiApiKey.ts`, `useVersionLog.ts`,
  `useUpdateCheck.ts`, `useSharedUrl.ts`, `useMainTab.ts` (the tab as a URL
  property: `/app?view=…`), `backNavigation.ts` + `useHardwareBack.ts`,
  `useResultExport.ts`, `useSoftKeyboard.ts`, `useSystemBarsTheme.ts`,
  `nativeFontScale.ts`, `landingRedirect.ts` and `firstRunScripts.ts`
  (pre-paint inline scripts, strings not hooks), `useFirstRun.ts`.
  Components never call an adapter directly.
- **`app/` + `components/`** — framework-bound presentation. `app/` holds
  only what Next.js requires (route files, `manifest.ts`, global CSS:
  `tokens.css` is the design-token sheet, `globals.css` the shared class
  vocabulary, `landing.css`/`first-run.css` the two one-offs). Routes: `/` is
  the landing page (`app/page.tsx` → `components/LandingScreen.tsx`; inside
  the installed app, and for legacy `/?view=…`/share links, it redirects to
  `/app` before paint via `application/landingRedirect.ts`); `/app` is the
  tool (`app/app/page.tsx` → `RoutedHomeScreen` plus the installed-app-only
  `Splash` and once-only `Welcome`); `/offline`, `/privacy`, `/terms`, and
  `not-found.tsx`. The manifest keeps `id: "/"` with `start_url: "/app"`.
  Full table in `frontend/ARCHITECTURE.md`. `components/HomeScreen.tsx` is
  the real page body (composes `useAnalysisRun()` with the presentational
  pieces); the chrome is **two shells** chosen pre-paint by `<html
  data-shell>` (`components/shell.ts`): `web` (top bar `AppNav` with the
  four tabs, `SiteFooter`) and `app` (installed PWA / Capacitor, phone width:
  `BottomTabBar` with Analyze, History, More, and `MoreSheet` holding API
  key, Releases, Privacy, Terms, theme). `components/panels/{ApiKeyPanel,
  HistoryPanel,VersionLogPanel}.tsx` are one-per-tab. Visual system:
  `docs/frontend/design-direction-editorial.md`; read it before any UI work.

Adding something new: new client state/API call → hook in `application/`,
port in `domain/ports.ts` if it talks externally, adapter in
`infrastructure/`, registered in `container.ts`. New tab/panel → component
in `components/panels/`, add the id to `MAIN_TABS` in `useMainTab.ts`, its
label to `TAB_LABEL` in `AppNav.tsx`, a row in `MoreSheet.tsx` if it
belongs in the installed shell, and its `<section className="tab-view">` in
`HomeScreen.tsx`.

## How a run flows

1. A fresh anonymous client first calls `GET /api/free-runs`, which issues a
   signed, stateless device token (`X-Device-Token`) and reports today's
   allowance (`FREE_RUNS_PER_DEVICE`, default 3/day, `FREE_RUNS_PER_IP` as a
   backstop). BYOK callers skip this.
2. Frontend `POST /api/runs` (multipart: `file` XOR `url`) → `202` with
   `{ run_id, status: "queued" }` after validating an uploaded file.
   Requires `X-Client-ID` (scopes visible runs, not quota) and
   `accept_terms=true`. Refusals: `400` validation, `401
   device_token_invalid`, `402 free_runs_used`, `429` per-IP rate limit, `503`
   daily cap or scheduling failure; the 429/503s carry `Retry-After`.
3. For URL runs, backend fetches via the resolver chain (yt-dlp, then direct
   HTTP), capped at `YTDLP_MAX_HEIGHT` (720p). yt-dlp's post metadata
   (`SourceMetadata`: title, uploader, caption, counts) is persisted
   immediately and handed to Gemini as fenced, untrusted context. Either way:
   validate + normalize with FFmpeg → upload to Gemini → analyze
   (`GEMINI_MODEL`, transient-error retries, then `GEMINI_FALLBACK_MODEL` if
   set).
4. If every resolver fails on a URL, the pipeline tries the subtitle track
   (`MediaProcessor.fetch_captions`) before giving up; a hit completes the
   run text-only with `completeness: "captions_only"` and stage
   `analyzing_captions`. Any failure there re-raises the original download
   error.
5. Alongside normalize/analyze, the backend makes a thumbnail **server
   side** (`infrastructure/media/thumbnails.py`, behind
   `MediaProcessor.describe_visuals`): yt-dlp's thumbnail URL fetched through
   the SSRF guard, else a frame from the media (uploads included), JPEG
   ≤320px / ≤20 KB; plus rotation-aware `width`/`height`. Audio and failed
   runs get none. A thumbnail failure never fails a run.
6. Frontend polls `GET /api/runs/{run_id}` until `status` is `complete` or
   `failed`; `stage` (only set while `processing`) is one of `downloading`,
   `normalizing`, `uploading_to_gemini`, `analyzing`, `analyzing_captions`.
   The detail carries `result`, `source_metadata`, `completeness`,
   `source_kind`, `platform`, `duration_seconds`, `thumbnail` (data URL),
   `width`, `height`, `orientation`. A free run is refunded when a link run
   was rejected before analysis (download failed, or over the duration cap).
7. **History lives in the browser**, not on the server: the frontend writes
   each run into IndexedDB (`infrastructure/historyStore.ts`, via
   `application/historySync.ts`) on submit, on each status change, and with
   the full result on completion — capped at 20, oldest dropped first, and
   reopened from there (works offline). It calls `navigator.storage.persist()`
   once. The browser may still evict it (e.g. Safari after 7 days unvisited,
   unless added to the Home Screen).
8. The server keeps a run only to deliver it: Redis/in-memory entries expire
   `RUN_TTL_SECONDS` (default **3600**, one hour) after the last write, and
   the TTL is refreshed when the run completes or fails. `GET /api/runs`
   still exists (the web app only uses it for a one-time import; the MCP
   server's `list_recent_runs` uses it) and therefore only sees the last
   hour.

Other endpoints: `GET /api/health` (liveness, `{"status":"ok"}`),
`GET /api/readiness` (Redis ping, 503 when storage is down), `GET
/api/capabilities` (per-dependency state — `media_tools`, `url_download`,
`analysis_engine`, `run_store`, `object_storage`, `daily_budget` — always
200; the frontend shows a notice before anyone uploads), `GET /api/releases`
(the GitHub release index read server-side with `GITHUB_TOKEN`, feeding the
Releases tab and the Android update check).

Local dev can run entirely in-process (no Redis/arq); production mode uses
Redis + arq worker + S3-compatible storage. Uploaded/downloaded files are
deleted after every run, success or failure.

### Bring-your-own-key (BYOK)

The API key tab (a nav tab on the web, a More-sheet row in the installed
app) lets a user paste their own Gemini key, stored only in browser
`localStorage`, sent as `X-Gemini-Api-Key`. Backend never writes it to
`RunStore` or logs it. In distributed mode it can't travel as a normal arq job
argument (arq logs job args), so it's held in a single-use Redis entry
(`infrastructure/byok/key_vault.py`) keyed by `run_id`, deleted the instant
the worker reads it, with a 15-minute safety-net TTL. BYOK runs are exempt
from `DAILY_RUN_CAP` and the free-run allowance but still subject to the
normal per-IP rate limit.

### MCP server (`mcp/`, branch `feature/mcp-server`)

Lets terminal AI agents (Claude Code, Cursor, Codex, Antigravity, ...) call
VideoLens directly via two tools: `analyze_video` (blocks until the run
finishes, returns the parsed result) and `list_recent_runs`. It's a thin
Node/TypeScript REST client over the same `POST /api/runs` /
`GET /api/runs{,/{run_id}}` endpoints the frontend uses — no new backend
surface, no shared use-case code (matches `frontend/infrastructure/
runsGateway.ts`'s role, different transport). It predates free runs and
`/api/capabilities`; because BYOK is mandatory there, device tokens do not
apply to it, but re-check it against the current API before merging.

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
Gemini spend. Four independent layers, all checked before any download/FFmpeg
work happens: `RATE_LIMIT_PER_HOUR` (per-IP or per-token, Redis-backed
across replicas when `REDIS_URL` is set, answers `429`), the per-device
free-run allowance (`FREE_RUNS_PER_DEVICE` / `FREE_RUNS_PER_IP`, answers
`402`; needs `DEVICE_TOKEN_SECRET` in distributed mode or the API refuses to
start), `DAILY_RUN_CAP` (global backstop across all callers, UTC day,
answers `503`), and the BYOK exemption from the last two.
`ALLOWED_ORIGINS` must never be `*` in production — the backend logs a
startup warning if it detects a distributed deployment still running with
`*`. The Capacitor WebView's `https://localhost` origin is allowed
unconditionally in code (`NATIVE_APP_ORIGINS`), not via configuration.

## Configuration

See `backend/.env.example` and `frontend/.env.example`. Key backend
settings: `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.6-flash`),
`GEMINI_FALLBACK_MODEL` (optional; retry tuning via `GEMINI_RETRY_ATTEMPTS`
/ `GEMINI_RETRY_MAX_DELAY_SECONDS`), `MAX_FILE_SIZE_MB` (200),
`MAX_DURATION_SECONDS` (180), `RATE_LIMIT_PER_HOUR` (20), `DAILY_RUN_CAP`
(200), `FREE_RUNS_PER_DEVICE` (3), `FREE_RUNS_PER_IP` (10),
`DEVICE_TOKEN_SECRET`, `RUN_TTL_SECONDS` (3600), `WORKER_MAX_JOBS`,
`WORKER_JOB_TIMEOUT_SECONDS`, `TEMP_DIR`, `FFMPEG_LOCATION`,
`YTDLP_MAX_HEIGHT` (720), `REDIS_URL`, `S3_*` (including
`S3_ADDRESSING_STYLE`: `auto`/`path`/`virtual`; Railway buckets need the
style their Credentials tab names), optional `AUTH_*` OIDC settings plus
`ALLOW_ANONYMOUS`, `ALLOWED_ORIGINS`, `GITHUB_TOKEN`/`GITHUB_REPO` (read-only
Contents access; blank makes `/api/releases` inert). Login-gated URL sources
(some Instagram links etc.) need either `YTDLP_COOKIES_FROM_BROWSER` (local)
or `YTDLP_COOKIES_FILE` pointing at a mounted Netscape-format cookie file
(deployed) — configure only one, and never commit a cookie file. The
frontend has one variable, `NEXT_PUBLIC_API_BASE_URL`, inlined at build
time, so a frontend image or APK is bound to one backend.

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
after this ships. Early exploration exists on the parked
`feat/paid-tier-integration` branch.

## Deployment

Railway, one project with `dev` and `production` environments tracking the
`dev` and `main` branches, each running backend (`backend/railway.json`),
worker (`backend/railway.worker.json`, same image and vars as the API),
frontend (`frontend/railway.json`), Redis and a bucket. Railway builds from
source; the GHCR images CI publishes are an archive, not what deploys.
Point the frontend's `NEXT_PUBLIC_API_BASE_URL` at the deployed backend and
set backend `ALLOWED_ORIGINS` to the deployed frontend origin. See
`DEPLOYMENT.md` for variables and what's still required before public
release (OIDC provider choice, production domains/secrets, Android signing
key, Play Console setup), and `docs/railway-environments.md` for deploy
triggers.

## Commit and PR message conventions

Plain messages only. **Never append attribution or session trailers** to a
commit message, PR title, PR body or PR/issue comment: no `Co-Authored-By:
Claude ...`, no `Claude-Session: https://claude.ai/code/...`, no "Generated
with Claude Code" footer or link, and no model identifier anywhere in anything
pushed to the repository. The owner asked for this explicitly (2026-11-06) and
it overrides any harness default that says to add such lines. Subject line in
the imperative, a short body when the why is not obvious, nothing else.

Branch flow: feature branch → PR into `dev` → promotion PR `dev` → `main`.
No direct pushes to either; the PR is the gate.

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
- **Change a service's trigger branch in the Railway dashboard only.** The
  API/MCP path (`connect_service_source`) applies the branch at service
  level across every environment; it moved `dev` onto `main` once
  (2026-08-29). See `docs/railway-environments.md`.
