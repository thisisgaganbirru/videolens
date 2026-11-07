# VideoLens AI Deployment

Last updated: November 7, 2026

Since the previous version of this plan (August 15, 2026) the following have
shipped and are reflected below: per-device **free runs** with signed device
tokens (and the `DEVICE_TOKEN_SECRET` they require), the **capabilities**
endpoint, the **release index** endpoint (which retired the bot commit that
used to write `version.json` into the repo), the **caption-only fallback** for
links whose video cannot be fetched, the server-side **history thumbnail**,
the CI redesign into three lanes (2026-10-29), the first promotion through the
production lane (2026-11-06, version 2.2.0), the landing page at `/` with the
tool at `/app`, and the Editorial redesign with its installed-app shell. The
project's name ("VideoLens AI") is under active review and may change before
public release — package ID, domains, and Play Store listing all depend on
that decision landing first; nothing below assumes a specific outcome.

## Decision

Release VideoLens AI in two stages:

1. Deploy and validate the production web application.
2. Package the proven web frontend as an Android application with Capacitor.

The Android application will remain a client of the hosted backend. Media
downloads, FFmpeg processing, Gemini requests, API keys, quotas, and
temporary files must not be moved into the mobile application.

## Target Architecture

```text
Web browser / installed PWA / Android app
           |
           | HTTPS
           v
Next.js frontend (static shell; History lives in the browser's IndexedDB)
           |
           | GET  /api/free-runs        (device token + today's allowance)
           | POST /api/runs
           | GET  /api/runs/{run_id}
           | GET  /api/runs             (one-time import only)
           | GET  /api/capabilities     (what works, before uploading)
           | GET  /api/releases         (Releases tab, Android update check)
           v
FastAPI backend (interface/api)
           |
           v
application/ use cases  ->  domain/ (rules, entities, ports)
           |
           v
infrastructure/ adapters
  |-- resolver chain: yt-dlp, then direct HTTP (all through one SSRF guard)
  |-- caption fallback when the media itself cannot be fetched
  |-- validation and FFmpeg normalization; server-side thumbnail
  |-- Gemini upload and analysis (retries, optional fallback model)
  |-- free-run allowance + HMAC device tokens (Redis)
  |-- BYOK key vault (single-use, never logged)
  |-- GitHub Releases (server-side token)
  `-- temporary-file cleanup
```

Production separates API handling from background processing, and the arq
worker is its own deployable service, not a thread inside the API:

```text
FastAPI API -> Redis queue -> arq worker -> Redis run state (RUN_TTL_SECONDS)
                                  |
                                  v
                          BYOK key vault (Redis, single-use, 15 min TTL)
```

See `backend/ARCHITECTURE.md` for the full layer breakdown and
`docs/backend/` for per-feature reference docs (auth, BYOK, free runs,
cost/abuse protection, run storage, job queue, capabilities, releases, etc.)
— this plan stays focused on what's required to *release*, not how each piece
works internally.

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
- [x] Per-device free runs (`FREE_RUNS_PER_DEVICE`, `FREE_RUNS_PER_IP`)
      shipped 2026-11-01 (`docs/backend/free-runs.md`). The API refuses to
      start in distributed mode without `DEVICE_TOKEN_SECRET` on both the
      backend and worker services, so the healthy 2026-11-06 production
      deploy implies it is set; confirm from the Railway dashboard rather
      than from this checkbox.
- [x] Abandoned runs are reported as failed instead of polling forever
      (`GetRunUseCase` staleness backstop, arq cancellation handling).
- [x] `GET /api/capabilities` reports which dependencies work, and the app
      shows it before anyone uploads; `GET /api/readiness` for the
      platform health check.
- [x] `GET /api/releases` serves the release index server-side
      (`GITHUB_TOKEN`), so no workflow commits to the repository.
- [x] Security headers on every API response and a hash-based CSP on the
      web and Android builds; WebView storage excluded from Android backups;
      client IP taken only from the proxy-written `X-Forwarded-For` entry;
      read endpoints rate-limited (2026-11-07 security pass, tracked in
      `VideoLens-Security-Assessment-2026-11-07.xlsx`).
- [ ] Set the four `ANDROID_*` release-signing secrets before the next push
      to `main`; the production lane fails without them (see "Android
      release signing" below).

### Operational Constraints

- Do not advertise support for every social-media URL. Platform
  authentication and downloader behavior change frequently; yt-dlp is
  pinned by hash and bumped weekly by Dependabot, and the `url_download`
  capability probe flags a copy older than 120 days.
- Never commit Gemini credentials, browser cookies, a `cookies.txt` file, or
  a user's BYOK key.
- Production cookies, if legally and operationally required, must be mounted
  as a secret and periodically rotated.
- Local mode uses in-memory runs and an in-process BYOK dict. Production must
  configure Redis, object storage, and the worker before scaling to multiple
  backend replicas — the BYOK key vault and the free-run counters
  specifically depend on Redis to cross the API/worker process boundary
  safely, and every replica must share `DEVICE_TOKEN_SECRET` or they reject
  each other's device tokens.
- `ALLOWED_ORIGINS` must never be `*` in a distributed (`REDIS_URL` set)
  deployment; since 2026-11-07 the backend refuses to start if it is. The
  Capacitor WebView's `https://localhost` origin is allowed in code and does
  not belong in this variable.
- Free runs are easy to bypass by design (clearing storage mints a new
  device; the per-IP backstop is the only thing behind that). They limit
  casual spend, not a determined abuser; `DAILY_RUN_CAP` and the key's own
  quota alert are what actually bound the bill.

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
`S3_*`, `DEVICE_TOKEN_SECRET`, and media-processing variables as the backend
service — it's the process that actually downloads, normalizes, and analyzes
the video.

Railway supports separate root directories for isolated monorepo services and
uses a service Dockerfile when present:

- [Railway monorepo deployment](https://docs.railway.com/deployments/monorepo)
- [Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles)

### Current Railway state

This exists already (created 2026-08-13) — don't recreate it, extend it.
None of the below is secret (IDs and URLs only; actual credentials live only
in Railway's variable store, never here). `docs/railway-environments.md` is
the living reference for this section; it holds the deploy-trigger semantics
and is updated whenever they are re-verified.

- **Account/workspace**: `gaganbirru's Projects`
  (`cae11393-e3fe-4c9c-a69b-3ae93206cab1`) — same account as the unrelated
  personal `relay-resume` project, kept isolated as a separate Railway
  project. Workspace-level spend limit: soft $15 / hard $25.
- **Project**: `videolens` (`7ad439b2-a26e-4e54-9233-f2c54afdece5`),
  `isPublic: false`, `prDeploys: false`.
- **Environments**: `dev` (`35fc5dbc-478a-4ebc-9ca8-ea5a75a9b267`) tracks
  branch `dev`; `production` (`e30dcf31-667e-43e1-b8c2-94882b8a9716`,
  created 2026-08-29 by forking `dev`) tracks `main`. Both autodeploy.
  **Wait for CI** is on for `production` (verified 2026-10-29; held the
  2026-11-06 promotion deploy until the production lane went green) and off
  for `dev`, where it is a no-op anyway because a push to `dev` runs no
  workflow; branch protection on the PR is the `dev` gate.
- **`dev` services**, each source-wired to `thisisgaganbirru/videolens`
  branch `dev`, `deploy.sleepApplication: true` (scale to zero when idle):
  - `videolens-backend` — `/backend` — `https://videolens-backend-dev.up.railway.app`
  - `videolens-worker` — `/backend`, `deploy.startCommand` overridden to
    `python -m arq app.worker.WorkerSettings` (no domain, not HTTP-facing)
  - `videolens-frontend` — `/frontend` — `https://videolens-frontend-dev.up.railway.app`
  - `Redis` — managed, wired via `${{Redis.REDIS_URL}}`, private network only
  - `videolens-dev-media` — S3-compatible bucket, region `iad`
- **`production` services**: the same, forked from `dev` with variables
  carried over, then corrected where they named the environment —
  `NEXT_PUBLIC_API_BASE_URL` (frontend) and `ALLOWED_ORIGINS` (backend) both
  point at the production URLs:
  - `videolens-backend` — `https://videolens-backend-production.up.railway.app`
  - `videolens-frontend` — `https://videolens-frontend-production.up.railway.app`
  - `videolens-worker`, `Redis`, bucket — as in `dev`
- **Status**: the 2026-11-06 promotion (version 2.2.0, release
  `v2.2.0-build350`) deployed to `production` once its lane went green
  (`docs/railway-environments.md`). The last recorded hands-on check was
  2026-08-29: `/api/health` 200, `mode: distributed`, every capability
  `ok`. Re-check `/api/readiness` and `/api/capabilities` before a release;
  this document is not a live status page.
- **Railway builds from source.** The GHCR images CI publishes are a
  scanned archive, not what deploys. Change a service's trigger branch in
  the dashboard only; the API path applies it across every environment.

### Environment-specific automation

Local workspace, dev, and production automation are intentionally separate.
`docker-compose.yml` is local-only. Pull requests into `dev` run only the
checks a change touches, with an advisory security scan and, when
`frontend/` changed, a dev-flavoured APK kept 14 days as a workflow artifact;
a merge into `dev` runs nothing and Railway deploys it. The promotion PR into
`main` runs the full checks with the security scan enforced, and the merge
builds each production image once, scans it, publishes it behind the
protected GitHub `production` environment (whose `PRODUCTION_API_BASE_URL`
variable is baked into the frontend image), builds the APK against the
production backend, and publishes the GitHub Release. `dev` publishes no
images.

No GitHub workflow deploys Railway at all, in either environment, and that is
by design: Railway builds from the repository itself and the published images
are an archive. `Wait for CI` is what ties them together — Railway holds a
push-triggered deploy until every workflow on that commit succeeds, so a
commit failing the container scan never reaches a running service. See
`docs/railway-environments.md` for the topology and `docs/container-workflows.md`
for the source files, tags, gates, and operator setup.

### Backend & Worker Variables

Configure these as Railway service variables on **both** the backend and
worker services (unless noted otherwise). Defaults are in
`backend/.env.example`.

```env
GEMINI_API_KEY=<secret>
GEMINI_MODEL=gemini-3.6-flash
# Optional second model tried once GEMINI_MODEL has exhausted its 429/5xx
# retries (GEMINI_RETRY_ATTEMPTS=6, GEMINI_RETRY_MAX_DELAY_SECONDS=20).
GEMINI_FALLBACK_MODEL=
RATE_LIMIT_PER_HOUR=20
# Looser per-IP limit on the read endpoints (polling, run list, free-runs).
READ_RATE_LIMIT_PER_MINUTE=120
# Trailing X-Forwarded-For entries written by the platform's own proxy; the
# client IP is that many from the end. 1 on Railway. 0 = use the socket peer.
TRUSTED_PROXY_HOPS=1
MAX_FILE_SIZE_MB=200
MAX_DURATION_SECONDS=180
# Tallest video yt-dlp fetches for a URL run; FFmpeg re-encodes anyway.
YTDLP_MAX_HEIGHT=720
# Global daily backstop across ALL callers, UTC day. 0 disables it.
DAILY_RUN_CAP=200
# Anonymous free runs per device / per IP, per UTC day (BYOK runs exempt).
FREE_RUNS_PER_DEVICE=3
FREE_RUNS_PER_IP=10
# REQUIRED while REDIS_URL is set and FREE_RUNS_PER_DEVICE > 0 (the API
# refuses to start without it). Same value on backend and worker. Generate
# with: python -c "import secrets; print(secrets.token_urlsafe(32))"
# Rotating it re-issues every device a token and resets today's counts.
DEVICE_TOKEN_SECRET=<secret>
# How long a run (and its entry in a caller's history list) stays in Redis
# after its last write. 1 hour: the browser keeps History (IndexedDB), so
# the server only holds a run until it is delivered.
RUN_TTL_SECONDS=3600
# Worker-only in effect, but harmless to set on both:
WORKER_MAX_JOBS=2
WORKER_JOB_TIMEOUT_SECONDS=600
TEMP_DIR=/tmp/videolens
ALLOWED_ORIGINS=https://app.example.com
REDIS_URL=<Railway Redis URL>
# On Railway, reference the environment's bucket service instead of pasting
# values, so a rotated key or the hashed bucket name can never go stale
# (the dev bucket is videolens-dev-media):
S3_ENDPOINT_URL=${{videolens-dev-media.ENDPOINT}}
S3_REGION=${{videolens-dev-media.REGION}}
S3_BUCKET=${{videolens-dev-media.BUCKET}}
S3_ACCESS_KEY_ID=${{videolens-dev-media.ACCESS_KEY_ID}}
S3_SECRET_ACCESS_KEY=${{videolens-dev-media.SECRET_ACCESS_KEY}}
# Use the URL style the bucket's Credentials tab names. Buckets created before
# Railway moved to virtual-hosted URLs (videolens-dev-media, 2026-08-13) need
# `path`; newer ones take `virtual`. The wrong one is a bare 403 on HeadBucket.
S3_ADDRESSING_STYLE=path
# Backend only: read access to this repository's releases for
# GET /api/releases (the Releases tab and the Android update check). A
# fine-grained token with read-only Contents access. Blank = the endpoint
# returns an empty index and update checks no-op.
GITHUB_TOKEN=<secret>
GITHUB_REPO=thisisgaganbirru/videolens
AUTH_JWKS_URL=<OIDC JWKS URL>
AUTH_ISSUER=<OIDC issuer>
AUTH_AUDIENCE=<OIDC audience>
ALLOW_ANONYMOUS=true
```

Do not set the local Windows `FFMPEG_LOCATION` value in production. The
backend Dockerfile installs FFmpeg into the container's executable path.

A variable change triggers a Railway redeploy that `Wait for CI` evaluates
against the currently deployed commit; if that commit has a failed workflow
the change silently never takes effect (`docs/railway-environments.md`).

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

Because this value is inlined into the browser bundle at build time, configure
it before building the frontend image. A frontend image or APK is therefore
bound to one backend and cannot be promoted between environments.

### Domains

Recommended production domains:

```text
app.example.com -> frontend service
api.example.com -> backend service
```

Both must use HTTPS. Set `ALLOWED_ORIGINS` to the exact frontend origin.
(These placeholder domains stand in until the project-name decision is
final — see the note at the top of this document. Today both environments
run on their `*.up.railway.app` domains.)

### Capacity

FFmpeg may temporarily hold an original download, separate video and audio
streams, a merged file, and a normalized file. A 200 MB input can therefore
require much more than 200 MB of temporary storage. `YTDLP_MAX_HEIGHT=720`
keeps URL downloads smaller than they would otherwise be. Railway's Free plan
currently provides 0.5 GB RAM and 1 GB ephemeral storage per service, so
production testing may require a paid plan or lower file limits — and now
that the worker is its own service, this budget applies separately to the
worker, not shared with the API service.

- [Railway pricing and resource limits](https://docs.railway.com/pricing/plans)
- [Railway ephemeral storage](https://docs.railway.com/services#ephemeral-storage)

### Web Release Verification

- [ ] `GET /api/health` returns `{"status":"ok"}`; `GET /api/readiness`
      reports `mode: distributed`; `GET /api/capabilities` reports every
      row `ok` (or `disabled` only where intended).
- [ ] File upload works from the production frontend.
- [ ] At least one public URL completes successfully, with a thumbnail and
      source metadata on the result.
- [ ] Private/login-only URLs return a concise, safe error; a URL whose
      video is blocked but whose captions are available completes as
      `captions_only` and the result says so.
- [ ] Transcript and on-screen text show timestamped timelines.
- [ ] Markdown rendering, copying, downloading and sharing work on mobile and
      desktop.
- [ ] A 21st run from the same quota identity receives HTTP 429 with
      `Retry-After`.
- [ ] A fresh device gets 3 free runs; the 4th receives HTTP 402; a forged
      `X-Device-Token` receives 401 and the app recovers by fetching a new
      one; a failed link download refunds the run.
- [ ] Runs survive API and worker restarts once Redis and the worker are
      enabled; a run whose worker died is reported `failed`, not
      `processing` forever.
- [ ] `GET /api/runs` returns the caller's own runs, newest first, capped
      at 20, and does not leak another caller's runs.
- [ ] Pasting a BYOK Gemini key via the API key tab produces a run that is
      exempt from `DAILY_RUN_CAP` and the free-run allowance but still
      subject to `RATE_LIMIT_PER_HOUR`.
- [ ] A BYOK key never appears in run records, logs, or the `GET
      /api/runs/{run_id}` response.
- [ ] `GET /api/releases` returns the release index (not empty), and the
      Releases tab lists it.
- [ ] No API keys, cookies, local paths, or terminal color codes appear in
      responses.

## Phase 3: Installable PWA

Add Progressive Web App support before producing the Android package:

- [x] Add a web app manifest with name, short name, colors, and standalone
      display (`id: "/"`, `start_url: "/app"`).
- [x] Add 192x192 and 512x512 application icons.
- [x] Add an application icon suitable for a maskable launcher shape.
- [x] Cache only the application shell and static assets (the service worker
      is generated per build so its precache list carries the real hashed
      chunk names).
- [x] Do not cache API run responses or uploaded media.
- [x] Provide a useful offline state (`/offline`; History works offline).
- [x] An installed-app shell (bottom tab bar, More sheet) distinct from the
      browser-tab chrome, chosen before first paint.
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
      production Play Store submission). Dev-lane APKs use
      `ai.videolens.app.dev` so they install beside the production app.
- [x] Configure the production API URL: `production-environment.yml` bakes
      `https://videolens-backend-production.up.railway.app` into the release
      APK. Revisit when a custom domain lands.
- [x] Use Android's native media picker for MP3, MP4, and MOV files.
- [x] Accept URLs shared from browsers and social applications.
- [x] Add native sharing for Markdown notes and result text; Save writes a
      real `.md` and opens the share sheet with the file.
- [x] Handle network loss and resumed run polling.
- [x] Add launcher icons, application name, and theme colors; follow the
      system theme and font scale natively; keep the status and gesture
      bars legible in both themes.
- [x] Installed-app shell: bottom tab bar (Analyze, History, More) and the
      More sheet (API key, Releases, Privacy, Terms, theme); hardware back
      walks the tabs and dialogs.
- [x] In-app update check against `GET /api/releases`, with a dismissable
      prompt linking to the release.
- [x] Release APKs published from `main` with a strictly increasing
      `versionCode` (commit count), signed with the CI-held release key
      since 2026-11-07 (the debug keystore stays for local and dev builds).
- [ ] Build and sign an Android App Bundle (`.aab`).
- [ ] Test on physical phones, tablets, small screens, and recent Android
      versions (manual suites: `docs/qa/android-app-test-cases.md`,
      `docs/qa/web-app-test-cases.md`).

The app should bundle its frontend assets and call the hosted API. Gemini
credentials, cookies, FFmpeg, and yt-dlp must never be included in the
Android package. BYOK keys entered on-device are sent only as a request
header to the hosted API, same as on web — never bundled or stored
server-side outside the single-use vault described in Phase 1.

### Android release signing

Since 2026-11-07 the production APK (every push to `main`,
`production-environment.yml` → `reusable-android-checks.yml` with
`upload_apk: true`) is a **release** build signed with a key that exists only
in GitHub Actions secrets. Before that it was the debug build signed with the
checked-in `frontend/android/debug.keystore` (password `android`), which meant
anyone with the repository could build an APK that installs as an update over
the real one, and the shipped app was debuggable. The debug keystore is still
used, on purpose, for local builds and the dev lane's `.dev` testing APK.

The production lane **fails** until these four repository secrets exist:

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | the release keystore file, base64-encoded (one line) |
| `ANDROID_KEYSTORE_PASSWORD` | the keystore password |
| `ANDROID_KEY_ALIAS` | the key alias inside it |
| `ANDROID_KEY_PASSWORD` | that key's password |

Create the keystore once, off the repository, and keep a backup somewhere
safe: losing it means every installed app has to be uninstalled and
reinstalled, since Android refuses an update signed with a different key.

```bash
keytool -genkeypair -v -keystore videolens-release.jks -alias videolens \
  -keyalg RSA -keysize 4096 -validity 10000
```

```bash
base64 -w0 videolens-release.jks | gh secret set ANDROID_KEYSTORE_BASE64
```

```bash
gh secret set ANDROID_KEYSTORE_PASSWORD
```

```bash
gh secret set ANDROID_KEY_ALIAS --body videolens
```

```bash
gh secret set ANDROID_KEY_PASSWORD
```

`frontend/android/app/build.gradle` reads `ANDROID_KEYSTORE_PATH`,
`ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` and `ANDROID_KEY_PASSWORD`
from the environment and configures release signing only when all four are
present; the workflow decodes the secret to `$RUNNER_TEMP/release.keystore`
and sets them for the Gradle step. Locally, export the same four variables
and run:

```powershell
cd frontend
npm run android:sync
cd android
.\gradlew.bat assembleRelease
```

**One-time migration for existing installs.** The first release-signed build
has a different signing identity from every APK published before it, so
Android will refuse to install it over an existing debug-signed install, and
the in-app update prompt will lead to an install error. Users have to
uninstall the old app once (History lives on the device and is lost; the
BYOK key too) and install the new one. Say so in that release's notes.

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
      request header, never persisted server-side), the anonymous device
      token (a random id, not tied to the device's identifiers), and the
      client id, when describing what data the app collects/transmits.
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
   *(OIDC verification, quotas and free runs done; provider selection/config
   outstanding)*
3. Deploy backend, worker, and frontend as three Railway services. *(done,
   both environments, on Railway domains)*
4. Test real production uploads and supported public URLs, including BYOK,
   free-run and caption-fallback flows. *(ongoing; the verification list
   above is the record)*
5. Add the PWA manifest, icons, and offline states. *(done)*
6. Add Capacitor and Android-native file/share integrations. *(done; debug
   APKs ship from `main` as GitHub Releases)*
7. Custom domains and the project-name decision.
8. Create a signed Android App Bundle.
9. Complete internal and closed Play Store testing.
10. Submit the Android application for production review.

## Definition of Done

The release is complete when:

- The public web application is available over HTTPS on a custom domain.
- Active runs are durable across API and worker restarts and deployments,
  and a run whose worker died is reported as failed.
- Backend concurrency and per-user quotas protect costs and capacity,
  including the free-run allowance and the `DAILY_RUN_CAP` global backstop.
- Uploaded and downloaded media is deleted according to the published
  policy; BYOK keys are never persisted beyond their single use.
- Run history is scoped correctly per caller, expires per
  `RUN_TTL_SECONDS` on the server, and persists in the browser.
- The PWA is installable and usable across supported mobile and desktop
  browsers.
- The Android application passes physical-device testing and Play
  pre-launch reports.
- The Play Store production release is approved and points to the same
  stable backend.
