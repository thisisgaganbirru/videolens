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

### With Docker Compose

```bash
cp backend/.env.example backend/.env   # fill in GEMINI_API_KEY
docker compose up --build
```

This starts the frontend, API, analysis worker, Redis, and MinIO. Frontend is
at `http://localhost:3000`, backend at `http://localhost:8000`, and the MinIO
console at `http://localhost:9001`.

## API

- `POST /api/runs` — multipart request with exactly one field: `file` (MP3,
  MP4, or MOV) or `url` (a public HTTP(S) media URL). Returns `{ run_id,
  status }` with `202 Accepted`. Upload validation errors return immediately;
  URL download errors are reported through run status. Requires
  `X-Client-ID`, `accept_terms=true`, and is rate limited per client or
  authenticated token (`RATE_LIMIT_PER_HOUR`, default 20/hour).
- `GET /api/runs/{run_id}` — returns
  `{ run_id, status, stage, result, error }`, where `status` is one of
  `queued`, `processing`, `complete`, `failed`, and `stage` (only set while
  `processing`) is one of `downloading`, `normalizing`,
  `uploading_to_gemini`, `analyzing`.

Run access is owner-bound. In distributed mode, Redis expires run state after
`RUN_TTL_SECONDS` (default 1 hour).

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
the exact version and commit it came from. CI additionally names the uploaded
workflow artifact after the same values (see the `android` job in
`.github/workflows/ci.yml`), downloadable from the Actions run summary.

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

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs backend tests,
TypeScript checks, production and mobile builds, and an Android API 36 build.

## Release gates

OIDC verification is implemented, but the operator must choose and configure an
identity provider before disabling anonymous access. Public release also requires
verified contact details in the Privacy Policy, production domains and secrets,
an Android signing key, Play Console declarations, physical-device testing, and
the required closed-test group. See `PUBLISHING_PLAN.md`.
