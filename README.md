# VideoLens AI

Upload short audio/video or paste a public media URL and get a transcript, on-screen text extraction, a
natural language summary, and formatted markdown notes — powered by Gemini's
multimodal video understanding, so it captures speech, on-screen text, code,
UI, and charts, not just audio.

Users can upload MP3, MP4, or MOV files directly, or submit a public URL from
a site supported by yt-dlp, including many Instagram, TikTok, and YouTube URLs.
Media is limited to 3 minutes and 200MB. Private, expired, region-blocked, or
login-only URLs may not be downloadable.

## How it works

1. The frontend sends either a media file or public URL to `POST /api/runs`,
   which immediately returns `{ run_id, status: "queued" }` after validating
   an uploaded file.
2. For URL runs, the backend downloads the media first. It then validates and
   normalizes audio/video with FFmpeg, uploads it to Gemini, and runs the analysis.
3. The frontend polls `GET /api/runs/{run_id}` until `status` is `complete`
   or `failed`.
4. On completion the run result contains `title`, `summary`, `transcript`,
   `screen_text`, and `markdown`.

Local development can use in-process run state. Production mode uses Redis,
an ARQ analysis worker, and S3-compatible temporary object storage. Uploaded
and downloaded files are deleted after every successful or failed run.

## Project layout

```
backend/             FastAPI API, worker, FFmpeg, Gemini, Redis/S3 adapters
frontend/            Next.js PWA and Capacitor source
frontend/android/    Android API 36 native project
```

## Running locally

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY
uvicorn app.main:app --reload
```

Requires `ffmpeg` and `ffprobe` on `PATH`, or set `FFMPEG_LOCATION` to the
directory containing both executables. The backend validates them during startup.

Some Instagram and other login-gated links require authenticated cookies. For
local development, set `YTDLP_COOKIES_FROM_BROWSER=chrome` (or your browser)
in `backend/.env`. For deployment, mount a Netscape-format cookie file as a
secret and set `YTDLP_COOKIES_FILE` to its path. Configure only one source.
Cookie files contain sensitive session data and must never be committed.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

The development server runs at `http://localhost:3005`; the backend allows
that origin by default.

### With Docker Compose

Docker Compose is the isolated **local workspace** workflow. It is not used to
deploy either hosted environment.

```powershell
cp backend/.env.example backend/.env   # fill in GEMINI_API_KEY
.\scripts\workspace.ps1 up
```

This starts the frontend, API, analysis worker, Redis, and MinIO. Frontend is
at `http://localhost:3000`, backend at `http://localhost:8000`, and the MinIO
console at `http://localhost:9001`. Use `verify`, `test`, `scan`, or `down` in
place of `up` for the other local lifecycle operations.

## API

- `POST /api/runs` — multipart request with exactly one field: `file` (MP3,
  MP4, or MOV) or `url` (a public HTTP(S) media URL). Returns `{ run_id,
  status }` with `202 Accepted`. Upload validation errors return immediately;
  URL download errors are reported through run status. Requires
  `X-Client-ID` (used only to scope which runs a browser can see, not for
  quota) and `accept_terms=true`. Rate limited per source IP, or per
  authenticated token when signed in (`RATE_LIMIT_PER_HOUR`, default
  20/hour). The limiter is Redis-backed when `REDIS_URL` is set, so the cap
  holds across replicas instead of resetting per process. A separate
  `DAILY_RUN_CAP` (default 200) bounds total accepted runs per UTC day
  across every caller, regardless of IP — the backstop against total Gemini
  spend once per-IP limits alone aren't enough. New runs are rejected with
  `503` once either cap is hit, before any download or FFmpeg work happens.
  An optional `X-Gemini-Api-Key` header (see "Bring your own key" below)
  exempts that run from `DAILY_RUN_CAP`, since it doesn't spend the shared
  quota; the per-IP/token rate limit still applies.
- `GET /api/runs/{run_id}` — returns
  `{ run_id, status, stage, result, error }`, where `status` is one of
  `queued`, `processing`, `complete`, `failed`, and `stage` (only set while
  `processing`) is one of `downloading`, `normalizing`,
  `uploading_to_gemini`, `analyzing`.
- `GET /api/runs` — returns `{ runs: [{ run_id, status, title, created_at }] }`,
  the caller's own run history (newest first, capped at 20). Backs the
  in-app History panel.

Run access is owner-bound. In distributed mode, Redis expires run state (and
each caller's history entries) after `RUN_TTL_SECONDS` (default 7 days).

### Bring your own key

The in-app menu's "API key" panel lets someone paste their own Gemini API key
(from [Google AI Studio](https://aistudio.google.com/apikey)). It's stored
only in the browser's `localStorage` and sent as `X-Gemini-Api-Key` on run
creation. The backend uses it in place of the shared `GEMINI_API_KEY` for
that run only:

- Never written to `RunStore` or logged.
- In distributed mode it can't travel as a normal background-job argument
  (arq logs job args/results), so it's held in a dedicated, single-use Redis
  entry (`backend/app/infrastructure/byok/key_vault.py`) keyed by `run_id`, deleted the instant the
  worker reads it, with a 15-minute safety-net TTL in case it's never read.
- Exempt from `DAILY_RUN_CAP` (that cap protects the shared key's spend, not
  a key someone brought themselves) but still subject to the normal per-IP
  rate limit, since FFmpeg/bandwidth/worker capacity are still spent either way.

## Use from an AI agent

`mcp/` is an MCP server so terminal AI agents (Claude Code, Cursor, Codex,
Antigravity, or any MCP client) can call VideoLens directly instead of going
through the web UI — two tools, `analyze_video` and `list_recent_runs`. It
requires your own Gemini API key (no shared-quota fallback, unlike the web
BYOK panel above — see `mcp/README.md` for why) supplied via your agent's
MCP config, never as a tool argument or file. Not yet published to npm;
`mcp/README.md` covers building and pointing your agent at the local build
in the meantime.

## Configuration

See `backend/.env.example` and `frontend/.env.example`. Key backend
settings: `GEMINI_API_KEY`, `GEMINI_MODEL`, `MAX_FILE_SIZE_MB`,
`MAX_DURATION_SECONDS`, `RATE_LIMIT_PER_HOUR`, `RUN_TTL_SECONDS`, `FFMPEG_LOCATION`,
`REDIS_URL`, the `S3_*` variables, optional `AUTH_*` OIDC settings, and
`ALLOWED_ORIGINS`.

## PWA and Android

The production frontend is an installable PWA with offline fallback, launcher
icons, and URL share-target support. API responses and submitted media are never
cached by the service worker.

Build and synchronize the Android application:

```bash
cd frontend
npm run android:sync
cd android
./gradlew assembleDebug testDebugUnitTest
```

The debug APK is written to
`frontend/android/app/build/outputs/apk/debug/videolens-ai-v<versionName>-code<versionCode>-<buildRef>-debug.apk`.
The Android app targets API 36, accepts text/URL shares, uses the native media
picker, and can share analysis results through the system share sheet. A
production `.aab` still requires an operator-owned signing key and Play Console
configuration.

### Versioning

`frontend/android/app/build.gradle` reads its `versionName` from
`frontend/package.json`'s `version` field — that's the single source of truth
for the app's semantic version. Bump it there for every release.

`versionCode` must strictly increase on every Play Store upload, so it's
supplied at build time rather than hardcoded:

- CI passes `-PappVersionCode=<GitHub Actions run number>`, which is always
  increasing across builds.
- Local builds without that property default to `versionCode 1`.

Both `versionName` and `versionCode`, plus the short git commit (`buildRef`),
are baked into the output APK's filename so any build can be traced back to
the exact version and commit it came from. The dedicated Android dev workflow
additionally names the uploaded artifact after the same values (see
`.github/workflows/android-development-build.yml`), downloadable from the Actions run
summary.

On every push to `dev`, CI also publishes the debug APK as a GitHub Release
(tagged `dev-v<versionName>-build<run number>`, marked pre-release) under the
repo's **Releases** page — a stable, non-expiring download link, unlike the
30-day workflow artifact.

### Debug signing

`frontend/android/debug.keystore` is checked into the repo (not a secret —
see the comment in `.gitignore`) and every debug build, local or CI, signs
with it via the `debug` block in `signingConfigs`. Without this, Android
Gradle Plugin falls back to an implicit `~/.android/debug.keystore` that's
auto-generated per machine — meaning every CI runner would sign with a
different key, and Android refuses to install a new APK over an existing
one when the signing certificate doesn't match. A stable debug identity is
what lets a newly downloaded APK actually install *as an update* over
whatever's already on the phone, instead of failing and requiring an
uninstall first.

### In-app update check

The app isn't distributed through Play Store, so nothing checks for updates
automatically — that's Play Store's job normally. `frontend/lib/updateCheck.ts`
does a lightweight version of it on native Android only: on launch, it reads
the installed app's `versionCode` via `@capacitor/app`'s `App.getInfo()`,
fetches the videolens GitHub repo's release list, and compares against the
`version.json` manifest attached to the newest release (see the "Write
version manifest" step in the `android` CI job). If a newer build exists,
`components/UpdateBanner.tsx` shows a banner linking to that release's page.
This is a check-and-link flow, not silent installation — Android doesn't
allow apps to install APKs without the user going through the system
installer UI outside of Play Store's own privileged path.

## Deployment

Production requires frontend, API, worker, Redis, and S3-compatible bucket
resources. Point the frontend's
`NEXT_PUBLIC_API_BASE_URL` at the deployed backend URL, and set
`ALLOWED_ORIGINS` on the backend to the deployed frontend origin.

- **Railway API**: use `backend/railway.json`.
- **Railway worker**: use `backend/railway.worker.json` with the same backend
  image and variables.
- **Railway frontend**: use `frontend/railway.json`.
- Provision Redis and an S3-compatible bucket, then share their variables with
  the API and worker services.

GitHub Actions is separated by environment and responsibility: pull requests
run application and container checks, `dev` publishes signed dev images and a
separate Android dev build, and `main` publishes signed production images only
after all checks and the protected `production` environment gate pass. See
`docs/container-workflows.md` for the exact workflow and deployment boundaries.

### Cost protection

The app has no accounts and no paid tier, so nothing gates the Gemini calls
that cost money except server-side limits. Before going live:

- Set `ALLOWED_ORIGINS` to your real frontend origin(s) — never leave it as
  `*` in production. The backend logs a startup warning if it detects a
  distributed deployment (`REDIS_URL` set) still running with `*`.
- Tune `RATE_LIMIT_PER_HOUR` and `DAILY_RUN_CAP` to what you're willing to
  spend per hour/day at your Gemini model's per-request price.
- Set a hard budget/quota alert on the Gemini API key itself in
  [Google AI Studio](https://aistudio.google.com/) or Google Cloud Console
  billing. This is the only layer enforced outside this app's own code — if
  every app-level limit above somehow fails or gets bypassed, this is what
  actually stops the bill.

## Release gates

OIDC verification is implemented, but the operator must choose and configure an
identity provider before disabling anonymous access. Public release also requires
verified contact details in the Privacy Policy, production domains and secrets,
an Android signing key, Play Console declarations, physical-device testing, and
the required closed-test group. See `DEPLOYMENT.md`.

## License

[GNU AGPL-3.0](LICENSE). If you run a modified version of this project as a
network service, you must make your modified source available to that
service's users — see the license text for the exact terms.
