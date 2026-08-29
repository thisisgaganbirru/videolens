# VideoLens AI Deployment

Last updated: August 15, 2026

Since the previous version of this plan, the backend was rewritten into
clean-architecture layers (`domain/` → `application/` →
`infrastructure/`/`interface/` — see `backend/ARCHITECTURE.md` and
`frontend/ARCHITECTURE.md` for the authoritative layering reference), and two
features shipped that this plan didn't yet account for: **bring-your-own-key
(BYOK)** and **run history**. Both are reflected below. The project's name
("VideoLens AI") is under active review and may change before public
release — package ID, domains, and Play Store listing all depend on that
decision landing first; nothing below assumes a specific outcome.

## Decision

Release VideoLens AI in two stages:

1. Deploy and validate the production web application.
2. Package the proven web frontend as an Android application with Capacitor.

The Android application will remain a client of the hosted backend. Media
downloads, FFmpeg processing, Gemini requests, API keys, quotas, and
temporary files must not be moved into the mobile application.

## Target Architecture

```text
Web browser / Android app
           |
           | HTTPS
           v
Next.js frontend
           |
           | POST /api/runs
           | GET  /api/runs/{run_id}
           | GET  /api/runs
           v
FastAPI backend (interface/api)
           |
           v
application/ use cases  ->  domain/ (rules, entities)
           |
           v
infrastructure/ adapters
  |-- media download with yt-dlp
  |-- validation and FFmpeg normalization
  |-- Gemini upload and analysis
  |-- BYOK key vault (single-use, never logged)
  `-- temporary-file cleanup
```

Production separates API handling from background processing, and the arq
worker is its own deployable service, not a thread inside the API:

```text
FastAPI API -> Redis queue -> arq worker -> Redis run state
                                  |
                                  v
                          BYOK key vault (Redis, single-use, 15 min TTL)
```

See `backend/ARCHITECTURE.md` for the full layer breakdown and
`docs/backend/` for per-feature reference docs (auth, BYOK, cost/abuse
protection, run storage, job queue, etc.) — this plan stays focused on what's
required to *release*, not how each piece works internally.

## Phase 1: Production Readiness

Complete these items before making the application publicly available.

### Required

- [x] Store production run state in Redis instead of process memory.
- [x] Execute downloads and analysis through a background worker queue (arq,
      deployed as its own Railway service — see `railway.worker.json`).
- [x] OIDC bearer-token verification is implemented (`JwtVerifier`,
      `AUTH_JWKS_URL`/`AUTH_ISSUER`/`AUTH_AUDIENCE`) but disabled by default
      (`ALLOW_ANONYMOUS=true`).
- [ ] Choose an OIDC provider, configure the three `AUTH_*` variables in
      production, and decide whether anonymous access stays enabled
      alongside it or gets turned off.
- [x] Bind anonymous quotas to a stable client ID and authenticated quotas to
      tokens.
- [x] Limit concurrent FFmpeg and Gemini operations in the worker
      (`WORKER_MAX_JOBS`, `WORKER_JOB_TIMEOUT_SECONDS`).
- [x] Make CORS origins explicit and configurable for production.
- [x] Add structured JSON logging; connect an external error monitor during
      deployment.
- [x] Remove temporary local and object-storage media after success or
      failure.
- [x] Add privacy and terms pages; replace placeholder operator contact
      before release.
- [x] Require a media permission and copyright acknowledgement before
      submission.
- [x] BYOK: caller-supplied Gemini keys never reach `RunRepository` or logs,
      and are single-use via a dedicated Redis entry with a 15-minute
      safety-net TTL (see `docs/backend/byok.md`).
- [x] Daily global spend backstop (`DAILY_RUN_CAP`) independent of per-caller
      rate limiting; BYOK runs are exempt from this cap since they don't
      spend the shared key, but remain subject to the normal rate limit.

### Operational Constraints

- Do not advertise support for every social-media URL. Platform
  authentication and downloader behavior change frequently.
- Never commit Gemini credentials, browser cookies, a `cookies.txt` file, or
  a user's BYOK key.
- Production cookies, if legally and operationally required, must be mounted
  as a secret and periodically rotated.
- Local mode uses in-memory runs and an in-process BYOK dict. Production must
  configure Redis, object storage, and the worker before scaling to multiple
  backend replicas — the BYOK key vault specifically depends on Redis to
  cross the API/worker process boundary safely.
- `ALLOWED_ORIGINS` must never be `*` in a distributed (`REDIS_URL` set)
  deployment; the backend logs a startup warning if it detects this.

## Phase 2: Deploy the Web Application

### Recommended Hosting

Use one Railway project with three isolated services from this repository —
the API and the worker are separate deployments sharing the same image and
environment variables, not one process:

| Service | Root directory | Config | Purpose |
| --- | --- | --- | --- |
| `videolens-backend` | `/backend` | `railway.json` | FastAPI: `interface/api`, routes, CORS, rate limiting |
| `videolens-worker` | `/backend` | `railway.worker.json` | arq worker: `python -m arq app.worker.WorkerSettings` — runs `ProcessRunUseCase` |
| `videolens-frontend` | `/frontend` | `railway.json` | Next.js user interface |

The worker service must set the *same* `GEMINI_API_KEY`, `REDIS_URL`,
`S3_*`, and media-processing variables as the backend service — it's the
process that actually downloads, normalizes, and analyzes the video.

Railway supports separate root directories for isolated monorepo services and
uses a service Dockerfile when present:

- [Railway monorepo deployment](https://docs.railway.com/deployments/monorepo)
- [Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles)

### Current Railway state

This exists already (created 2026-08-13) — don't recreate it, extend it.
None of the below is secret (IDs and URLs only; actual credentials live only
in Railway's variable store, never here):

- **Account/workspace**: `gaganbirru's Projects`
  (`cae11393-e3fe-4c9c-a69b-3ae93206cab1`) — same account as the unrelated
  personal `relay-resume` project, kept isolated as a separate Railway
  project. Workspace-level spend limit: soft $15 / hard $25.
- **Project**: `videolens` (`7ad439b2-a26e-4e54-9233-f2c54afdece5`),
  `isPublic: false`, `prDeploys: false`.
- **Environments**: `dev` (`35fc5dbc-478a-4ebc-9ca8-ea5a75a9b267`), the
  active test environment linked locally via `railway status`, and
  `production` (`e30dcf31-667e-43e1-b8c2-94882b8a9716`), created 2026-08-29
  by forking `dev`. `dev` tracks branch `dev`; `production` tracks `main`.
  Both have autodeploy and **Wait for CI** enabled — see
  `docs/railway-environments.md` for the trigger semantics and the three ways
  a deploy silently does not happen.
- **`dev` services**, each source-wired to `thisisgaganbirru/videolens`
  branch `dev`, `deploy.sleepApplication: true` (scale to zero when idle):
  - `videolens-backend` — `/backend` — `https://videolens-backend-dev.up.railway.app`
  - `videolens-worker` — `/backend`, `deploy.startCommand` overridden to
    `python -m arq app.worker.WorkerSettings` (no domain, not HTTP-facing)
  - `videolens-frontend` — `/frontend` — `https://videolens-frontend-dev.up.railway.app`
  - `Redis` — managed, wired via `${{Redis.REDIS_URL}}`, private network only
  - `videolens-dev-media` — S3-compatible bucket, region `iad`
- **`production` services**: the same four, forked from `dev` with variables
  carried over, then corrected where they named the environment —
  `NEXT_PUBLIC_API_BASE_URL` (frontend) and `ALLOWED_ORIGINS` (backend) both
  now point at the production URLs:
  - `videolens-backend` — `https://videolens-backend-production.up.railway.app`
  - `videolens-frontend` — `https://videolens-frontend-production.up.railway.app`
  - `videolens-worker`, `Redis` — as in `dev`
- **Status (verified 2026-08-29)**: both environments are deployed and
  healthy. The production backend serves `/api/health` 200 and reports
  `mode: distributed` with every capability `ok`. HTTP services sleep when
  idle and wake on request.

### Environment-specific automation

Local workspace, dev, and production automation are intentionally separate.
`docker-compose.yml` is local-only. Pull requests run reusable application and
container checks. The `dev` branch publishes signed `dev` container images and
has its own Android debug-release workflow. The `main` branch publishes signed
production images only after the protected GitHub `production` environment
allows it and `PRODUCTION_API_BASE_URL` is configured.

No GitHub workflow deploys Railway at all, in either environment, and that is
by design: Railway builds from the repository itself and the published images
are an archive. `Wait for CI` is what ties them together — Railway holds a
push-triggered deploy until every workflow on that commit succeeds, so a
commit failing the container scan never reaches a running service. See
`docs/railway-environments.md` for the topology and `docs/container-workflows.md`
for the source files, tags, gates, and operator setup.

### Backend & Worker Variables

Configure these as Railway service variables on **both** the backend and
worker services (unless noted otherwise):

```env
GEMINI_API_KEY=<secret>
GEMINI_MODEL=gemini-3.6-flash
RATE_LIMIT_PER_HOUR=20
MAX_FILE_SIZE_MB=200
MAX_DURATION_SECONDS=180
# Global daily backstop across ALL callers, UTC day. 0 disables it.
DAILY_RUN_CAP=200
# How long a completed run (and its entry in a caller's history list) stays
# in Redis. Default is 7 days now, not 1 hour — this is a real retention
# policy, not just a cache TTL. Bump to 2592000 for 30 days.
RUN_TTL_SECONDS=604800
# Worker-only in effect, but harmless to set on both:
WORKER_MAX_JOBS=2
WORKER_JOB_TIMEOUT_SECONDS=600
TEMP_DIR=/tmp/videolens
ALLOWED_ORIGINS=https://app.example.com
REDIS_URL=<Railway Redis URL>
S3_ENDPOINT_URL=<S3-compatible endpoint>
S3_REGION=auto
S3_BUCKET=videolens-media
S3_ACCESS_KEY_ID=<secret>
S3_SECRET_ACCESS_KEY=<secret>
AUTH_JWKS_URL=<OIDC JWKS URL>
AUTH_ISSUER=<OIDC issuer>
AUTH_AUDIENCE=<OIDC audience>
ALLOW_ANONYMOUS=true
```

Do not set the local Windows `FFMPEG_LOCATION` value in production. The
backend Dockerfile installs FFmpeg into the container's executable path.

If login-gated media is intentionally supported, configure only one cookie
method:

```env
YTDLP_COOKIES_FILE=/run/secrets/cookies.txt
```

Do not configure `YTDLP_COOKIES_FROM_BROWSER` on a hosted server.

### Frontend Variables

```env
NEXT_PUBLIC_API_BASE_URL=https://api.example.com
```

Because this value is used by the browser bundle, configure it before
building the frontend image.

### Domains

Recommended production domains:

```text
app.example.com -> frontend service
api.example.com -> backend service
```

Both must use HTTPS. Set `ALLOWED_ORIGINS` to the exact frontend origin.
(These placeholder domains stand in until the project-name decision is
final — see the note at the top of this document.)

### Capacity

FFmpeg may temporarily hold an original download, separate video and audio
streams, a merged file, and a normalized file. A 200 MB input can therefore
require much more than 200 MB of temporary storage. Railway's Free plan
currently provides 0.5 GB RAM and 1 GB ephemeral storage per service, so
production testing may require a paid plan or lower file limits — and now
that the worker is its own service, this budget applies separately to the
worker, not shared with the API service.

- [Railway pricing and resource limits](https://docs.railway.com/pricing/plans)
- [Railway ephemeral storage](https://docs.railway.com/services#ephemeral-storage)

### Web Release Verification

- [ ] `GET /api/health` returns `{"status":"ok"}`.
- [ ] File upload works from the production frontend.
- [ ] At least one public URL completes successfully.
- [ ] Private/login-only URLs return a concise, safe error.
- [ ] Transcript and on-screen text show timestamped timelines.
- [ ] Markdown rendering, copying, and downloading work on mobile and
      desktop.
- [ ] A 21st run from the same quota identity receives HTTP 429.
- [ ] Runs survive API and worker restarts once Redis and the worker are
      enabled.
- [ ] `GET /api/runs` returns the caller's own history, newest first, capped
      at 20, and does not leak another caller's runs.
- [ ] Pasting a BYOK Gemini key via the frontend's API key panel produces a
      run that is exempt from `DAILY_RUN_CAP` but still subject to
      `RATE_LIMIT_PER_HOUR`.
- [ ] A BYOK key never appears in run records, logs, or the `GET
      /api/runs/{run_id}` response.
- [ ] No API keys, cookies, local paths, or terminal color codes appear in
      responses.

## Phase 3: Installable PWA

Add Progressive Web App support before producing the Android package:

- [x] Add a web app manifest with name, short name, colors, and standalone
      display.
- [x] Add 192x192 and 512x512 application icons.
- [x] Add an application icon suitable for a maskable launcher shape.
- [x] Cache only the application shell and static assets.
- [x] Do not cache API run responses or uploaded media.
- [x] Provide a useful offline state.
- [ ] Test installation on Android Chrome and desktop Chrome/Edge.

An installable PWA appears in launchers and can run in its own application
window without requiring a Play Store package:

- [PWA installation guidance](https://web.dev/learn/pwa/installation)
- [PWA installability criteria](https://web.dev/articles/install-criteria)

## Phase 4: Android Application

Use Capacitor to package the existing frontend. Capacitor is designed to add
a native Android container and native APIs to an existing web application:

- [Capacitor documentation](https://capacitorjs.com/docs)

### Android Scope

- [x] Add Capacitor and create the Android project.
- [x] Use the stable package ID `ai.videolens.app` (revisit if/when the
      project rename lands — package ID changes are effectively a new app
      listing on Play, not a rename, so this should be locked before any
      production Play Store submission).
- [ ] Configure the production API URL.
- [x] Use Android's native media picker for MP3, MP4, and MOV files.
- [x] Accept URLs shared from browsers and social applications.
- [x] Add native sharing for Markdown notes and result text.
- [x] Handle network loss and resumed run polling.
- [x] Add launcher icons, application name, and theme colors.
- [x] In-app menu: API key (BYOK) panel, run history panel, version log
      panel.
- [ ] Build and sign an Android App Bundle (`.aab`).
- [ ] Test on physical phones, tablets, small screens, and recent Android
      versions.

The app should bundle its frontend assets and call the hosted API. Gemini
credentials, cookies, FFmpeg, and yt-dlp must never be included in the
Android package. BYOK keys entered on-device are sent only as a request
header to the hosted API, same as on web — never bundled or stored
server-side outside the single-use vault described in Phase 1.

Release signing is configured through `ANDROID_KEYSTORE_PATH`,
`ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, and
`ANDROID_KEY_PASSWORD`. The keystore and values must be stored outside Git.
With those values set, run:

```powershell
cd frontend
npm run android:sync
cd android
.\gradlew.bat bundleRelease
```

### Android Target

Target Android 16, API level 36. Google states that beginning August 31,
2026, new applications and updates submitted to Google Play must target API
36 or higher:

- [Google Play target API requirements](https://developer.android.com/google/play/requirements/target-sdk)

### Play Console Requirements

- [ ] Create and verify a Personal or Organization Play Console account.
- [ ] Verify access to a physical Android device if Google requests it.
- [ ] Create the store listing, privacy policy URL, screenshots, and feature
      graphic.
- [ ] Complete the Data safety form accurately — note the BYOK key panel
      (user-supplied, stored only in browser/app `localStorage`, sent as a
      request header, never persisted server-side) when describing what
      data the app collects/transmits.
- [ ] Complete the content rating and app-access declarations.
- [ ] Upload the signed `.aab` to internal testing first.
- [ ] Complete required closed testing before requesting production access.

For new Personal accounts created after November 13, 2023, Google currently
requires at least 12 testers to remain opted into a closed test continuously
for 14 days before the developer can apply for production access:

- [Google Play testing requirements](https://support.google.com/googleplay/android-developer/answer/14151465)
- [Google Play developer verification](https://support.google.com/googleplay/android-developer/answer/10841920)

## Release Order

1. Add Redis-backed run state and a background worker. *(done)*
2. Add authentication, per-user quotas, and production security controls.
   *(OIDC verification and quotas done; provider selection/config
   outstanding)*
3. Deploy backend, worker, and frontend as three Railway services.
4. Test real production uploads and supported public URLs, including BYOK
   and run-history flows.
5. Add the PWA manifest, icons, and offline states. *(done)*
6. Add Capacitor and Android-native file/share integrations. *(done)*
7. Create a signed Android App Bundle.
8. Complete internal and closed Play Store testing.
9. Submit the Android application for production review.

## Definition of Done

The release is complete when:

- The public web application is available over HTTPS on a custom domain.
- Active runs are durable across API and worker restarts and deployments.
- Backend concurrency and per-user quotas protect costs and capacity,
  including the `DAILY_RUN_CAP` global backstop.
- Uploaded and downloaded media is deleted according to the published
  policy; BYOK keys are never persisted beyond their single use.
- Run history is scoped correctly per caller and expires per
  `RUN_TTL_SECONDS`.
- The PWA is installable and usable across supported mobile and desktop
  browsers.
- The Android application passes physical-device testing and Play
  pre-launch reports.
- The Play Store production release is approved and points to the same
  stable backend.
