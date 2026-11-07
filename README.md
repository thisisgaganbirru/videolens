# VideoLens AI

Upload short audio/video or paste a public media URL and get a transcript, on-screen text extraction, a
natural language summary, and formatted markdown notes — powered by Gemini's
multimodal video understanding, so it captures speech, on-screen text, code,
UI, and charts, not just audio.

Users can upload MP3, MP4, or MOV files directly, or submit a public URL from
a site supported by yt-dlp, including many Instagram, TikTok, and YouTube URLs.
Media is limited to 3 minutes and 200MB. Private, expired, region-blocked, or
login-only URLs may not be downloadable. When a platform refuses to serve the
video but still serves its subtitles, the run completes from the caption track
alone and says so (`completeness: "captions_only"`).

It runs as a web app, an installable PWA, and an Android app (Capacitor), all
against the same backend. Current version: `2.2.0`.

## How it works

1. A fresh anonymous client calls `GET /api/free-runs` once to receive a
   signed device token and learn how many free runs it has today.
2. The frontend sends either a media file or public URL to `POST /api/runs`,
   which immediately returns `{ run_id, status: "queued" }` after validating
   an uploaded file.
3. For URL runs, the backend downloads the media first (yt-dlp, with a plain
   HTTP fetch as a fallback for links that point straight at a media file).
   It then validates and normalizes audio/video with FFmpeg, uploads it to
   Gemini, and runs the analysis. A thumbnail for the history card is made
   server side alongside.
4. The frontend polls `GET /api/runs/{run_id}` until `status` is `complete`
   or `failed`, and stores every state change in the browser's IndexedDB.
   History lives in the browser; the server forgets a run an hour after it is
   delivered.
5. On completion the run result contains `title`, `summary`, `transcript`
   (plus timestamped `transcript_segments`), `screen_text` (plus
   `screen_text_segments`), and `markdown`.

Local development can use in-process run state. Production mode uses Redis,
an arq analysis worker, and S3-compatible temporary object storage. Uploaded
and downloaded files are deleted after every successful or failed run.

## Project layout

```
backend/             FastAPI API, worker, FFmpeg, Gemini, Redis/S3 adapters
frontend/            Next.js PWA and Capacitor source
frontend/android/    Android API 36 native project
docs/                Per-feature reference docs (index in docs/README.md)
scripts/             workspace.ps1, the Docker Compose local-workspace lifecycle
.github/             CI lanes, composite actions, Dependabot
```

Both apps follow the same clean-architecture layering (`domain` →
`application` → `infrastructure` / `interface`); `backend/ARCHITECTURE.md` and
`frontend/ARCHITECTURE.md` are the reference. `CLAUDE.md` is the working guide
for anyone (or any agent) changing the code.

An MCP server (`mcp/`) that lets terminal AI agents call VideoLens directly
exists on the unmerged `feature/mcp-server` branch; see "Use from an AI
agent" below.

## Running locally

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY
uvicorn app.main:app --reload
```

Python 3.13 (see `.python-version`). Requires `ffmpeg` and `ffprobe` on
`PATH`, or set `FFMPEG_LOCATION` to the directory containing both
executables. The backend validates them during startup. `requirements.txt` is
a hash-locked, cross-platform compile of `requirements.in`; regenerate it with
`uv pip compile requirements.in --generate-hashes --python-version 3.13
--universal --output-file requirements.txt`, never with plain `pip-compile`
(it drops the platform markers and CI rejects the result).

Some Instagram and other login-gated links require authenticated cookies. For
local development, set `YTDLP_COOKIES_FROM_BROWSER=chrome` (or your browser)
in `backend/.env`. For deployment, mount a Netscape-format cookie file as a
secret and set `YTDLP_COOKIES_FILE` to its path. Configure only one source.
Cookie files contain sensitive session data and must never be committed.

Checks, in the order CI runs them:

```bash
python -m compileall -q app
python -m unittest discover -s tests
GEMINI_API_KEY=ci-test-key python -c "import app.main; import app.worker"
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Node 24 (see `.nvmrc`). The development server runs at
`http://localhost:3005`; the backend allows that origin by default.
`npx tsc --noEmit`, `npm run build` and `npm run build:mobile` are the checks
CI runs. `npm run lint` works but currently exits non-zero on four
pre-existing, deliberately unfixed findings (see `CLAUDE.md`).

### With Docker Compose

Docker Compose is the isolated **local workspace** workflow. It is not used to
deploy either hosted environment.

```powershell
cp backend/.env.example backend/.env   # fill in GEMINI_API_KEY
.\scripts\workspace.ps1 up             # or: docker compose up --build
```

This starts the frontend, API, analysis worker, Redis, and MinIO. Frontend is
at `http://localhost:3000`, backend at `http://localhost:8000`, and the MinIO
console at `http://localhost:9001`, all bound to loopback. Use `check`,
`verify`, `test`, `scan`, or `down` in place of `up` for the other local
lifecycle operations. See `docs/container-workflows.md`.

## API

- `POST /api/runs` — multipart request with exactly one field: `file` (MP3,
  MP4, or MOV) or `url` (a public HTTP(S) media URL), plus
  `accept_terms=true`. Returns `{ run_id, status }` with `202 Accepted`.
  Upload validation errors return immediately (`400`); URL download errors
  are reported through run status. Requires `X-Client-ID` (used only to
  scope which runs a browser can see, not for quota). Limits, checked in
  this order before any download or FFmpeg work:
  - Per source IP, or per authenticated token when signed in
    (`RATE_LIMIT_PER_HOUR`, default 20/hour): `429` with `Retry-After`.
    Redis-backed when `REDIS_URL` is set, so the cap holds across replicas.
  - Without a Gemini key of their own, the caller also needs
    `X-Device-Token` (from `GET /api/free-runs`) and gets
    `FREE_RUNS_PER_DEVICE` (default 3) runs per UTC day, with
    `FREE_RUNS_PER_IP` (default 10) as a per-network backstop:
    `401 {"code": "device_token_invalid"}` for a missing/forged token,
    `402 {"code": "free_runs_used", "limit", "used"}` once spent. A free run
    is refunded if the link could not be downloaded or was over the duration
    cap. See `docs/backend/free-runs.md`.
  - `DAILY_RUN_CAP` (default 200) bounds total accepted runs per UTC day
    across every caller, regardless of IP — the backstop against total
    Gemini spend: `503` with `Retry-After`.
  - An optional `X-Gemini-Api-Key` header (see "Bring your own key" below)
    exempts that run from the free-run allowance and `DAILY_RUN_CAP`, since
    it doesn't spend the shared quota; the per-IP/token rate limit still
    applies.
- `GET /api/free-runs` — `{ device_token, enabled, limit, used, remaining,
  resets_at }` for the device in `X-Device-Token`, issuing a new token when
  it is missing or not genuine. Read-only: never spends a run. Needs no
  `X-Client-ID`.
- `GET /api/runs/{run_id}` — `{ run_id, status, stage, result,
  source_metadata, completeness, error, source_kind, platform,
  duration_seconds, thumbnail, width, height, orientation }`. `status` is one
  of `queued`, `processing`, `complete`, `failed`; `stage` (only set while
  `processing`) is one of `downloading`, `normalizing`,
  `uploading_to_gemini`, `analyzing`, `analyzing_captions`.
  `source_metadata` is what yt-dlp knew about the post (title, uploader,
  caption, counts); `completeness` is `full` or `captions_only`; `thumbnail`
  is a ≤20 KB JPEG data URL. A run that stopped reporting progress for
  longer than the worker timeout is reported as `failed` rather than
  polling forever.
- `GET /api/runs` — `{ runs: [{ run_id, status, title, created_at,
  source_kind, platform, duration_seconds, summary_snippet, orientation,
  width, height }] }`, the caller's own runs still on the server (newest
  first, capped at 20). The web app uses it once, to import runs made before
  History moved into the browser.
- `GET /api/capabilities` — which parts of this deployment work right now
  (`media_tools`, `url_download`, `analysis_engine`, `run_store`,
  `object_storage`, `daily_budget`), each `ok`, `degraded`, `unavailable` or
  `disabled`, with whether it was actually probed. Always `200`; the app
  shows a notice before anyone uploads. See `docs/backend/capabilities.md`.
- `GET /api/releases` — the app's own GitHub release index, read server-side
  with `GITHUB_TOKEN` (the repo is private). Feeds the in-app Releases tab
  and the Android update check. Empty when no token is configured.
- `GET /api/health` — liveness, `{"status": "ok"}`. `GET /api/readiness` —
  pings run storage, `503` when it is down.

Run access is owner-bound. Run state (and each caller's history entries)
expires `RUN_TTL_SECONDS` after its last write (default 1 hour): the browser
keeps History itself, so the server only holds a run until it is delivered.
`GET /api/runs` therefore only sees the last hour.

Optional OIDC bearer tokens are verified when `AUTH_*` is configured
(`Authorization: Bearer …` becomes an authenticated principal); anonymous
access via `X-Client-ID` stays on unless `ALLOW_ANONYMOUS=false`.

### Bring your own key

The "API key" tab (a nav tab on the web, a row in the installed app's More
sheet) lets someone paste their own Gemini API key (from
[Google AI Studio](https://aistudio.google.com/apikey)). It's stored only in
the browser's `localStorage` and sent as `X-Gemini-Api-Key` on run creation.
The backend uses it in place of the shared `GEMINI_API_KEY` for that run only:

- Never written to `RunStore` or logged.
- In distributed mode it can't travel as a normal background-job argument
  (arq logs job args/results), so it's held in a dedicated, single-use Redis
  entry (`backend/app/infrastructure/byok/key_vault.py`) keyed by `run_id`, deleted the instant the
  worker reads it, with a 15-minute safety-net TTL in case it's never read.
- Exempt from `DAILY_RUN_CAP` and the per-device free-run allowance (both
  protect the shared key's spend, not a key someone brought themselves) but still subject to the normal per-IP
  rate limit, since FFmpeg/bandwidth/worker capacity are still spent either way.

## Use from an AI agent

`mcp/` is an MCP server so terminal AI agents (Claude Code, Cursor, Codex,
Antigravity, or any MCP client) can call VideoLens directly instead of going
through the web UI — two tools, `analyze_video` and `list_recent_runs`. It
requires your own Gemini API key (no shared-quota fallback, unlike the web
BYOK panel above) supplied via your agent's MCP config, never as a tool
argument or file.

It is **not on `dev` or `main` yet**: the source is parked on the
`feature/mcp-server` branch (together with the root `.mcp.json` it wires up)
until the frontend work settles, and it is not published to npm. That branch's
`mcp/README.md` covers building it and pointing an agent at the local build.

## Configuration

See `backend/.env.example` and `frontend/.env.example`. Key backend
settings: `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`,
`MAX_FILE_SIZE_MB`, `MAX_DURATION_SECONDS`, `RATE_LIMIT_PER_HOUR`,
`DAILY_RUN_CAP`, `FREE_RUNS_PER_DEVICE`, `FREE_RUNS_PER_IP`,
`DEVICE_TOKEN_SECRET` (required in distributed mode), `RUN_TTL_SECONDS`,
`YTDLP_MAX_HEIGHT`, `FFMPEG_LOCATION`, `REDIS_URL`, the `S3_*` variables
(including `S3_ADDRESSING_STYLE`), optional `AUTH_*` OIDC settings,
`ALLOWED_ORIGINS`, and `GITHUB_TOKEN` / `GITHUB_REPO` for `/api/releases`.
The frontend has one: `NEXT_PUBLIC_API_BASE_URL`, inlined at build time.

## PWA and Android

The production frontend is an installable PWA with offline fallback, launcher
icons, and URL share-target support. The service worker precaches the shell
documents and the build's hashed assets; API responses and submitted media are
never cached. The installed app (PWA or Android) gets a phone-style shell with
a bottom tab bar (Analyze, History, More); a browser tab gets a top nav with
all four tabs (Analyze, History, API key, Releases) and a footer.

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
picker, follows the system font scale and theme natively, and can share or
save analysis results through the system share sheet. A production `.aab`
still requires an operator-owned signing key and Play Console configuration.

Three kinds of APK exist, for three purposes:

- **Production**: every push to `main` builds the APK against the production
  backend and publishes it as a GitHub Release (tag
  `v<versionName>-build<versionCode>`). That is the only APK anyone installs
  for real, and the only one the in-app update check offers.
- **Dev / testing**: every PR into `dev` that touches `frontend/` builds the
  APK against the dev backend and keeps it as a 14-day workflow artifact
  (`videolens-ai-dev-v<version>-code<code>-<sha>`). It carries the `.dev`
  application id suffix and a `-dev` version name, so it installs beside the
  production app rather than over it. Never a release.
- **Local**: the commands above, for previews and device QA on a developer
  machine. Never shipped.

### Versioning

`frontend/android/app/build.gradle` reads its `versionName` from
`frontend/package.json`'s `version` field — that's the single source of truth
for the app's semantic version (the web app's Releases page reads the same
value as `NEXT_PUBLIC_APP_VERSION`). Bump it there for every release.

`versionCode` must strictly increase on every upload, so it's supplied at
build time rather than hardcoded:

- CI passes `-PappVersionCode=$(git rev-list --count HEAD)`, the commit
  count, which is a property of the history rather than of any one workflow
  and therefore keeps climbing even when publication moves between
  workflows (it was `github.run_number` once, and moving releases from `dev`
  to `main` would have reset it).
- Local builds without that property default to `versionCode 1`.

Both `versionName` and `versionCode`, plus the short git commit (`buildRef`),
are baked into the output APK's filename so any build can be traced back to
the exact version and commit it came from.

Builds 1-30 predate the move to `main` and are tagged
`dev-v<versionName>-build<code>`. The backend's release parser accepts both
forms so those releases stay readable by the in-app Releases tab and update
check.

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
automatically — that's Play Store's job normally.
`frontend/infrastructure/updateCheck.ts` does a lightweight version of it on
native Android only: on launch, it reads the installed app's `versionCode`
via `@capacitor/app`'s `App.getInfo()` and asks the app's own backend
(`GET /api/releases`) for the newest release. The backend reads GitHub with a
server-side token because the repository is private. If a newer build
exists, `components/UpdatePrompt.tsx` shows a modal linking to that
release's page; "Later" remembers the dismissed build. This is a
check-and-link flow, not silent installation — Android doesn't allow apps to
install APKs without the user going through the system installer UI outside
of Play Store's own privileged path. The release also carries a
`version.json` asset describing the build.

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

The repo is wired to one Railway project with two environments: `dev` tracks
the `dev` branch, `production` tracks `main`. Railway builds from source on
every push; "Wait for CI" holds a production deploy until the commit's
workflows are green.

GitHub Actions runs three independent lanes: pull requests into `dev` run only
the checks a change touches, with an advisory security scan; the promotion into
`main` runs the full checks with the security scan enforced, and the merge
builds, scans and publishes the production images and the Android release
behind the protected `production` environment; a nightly scan of `main` opens
an issue when a new vulnerability lands. See
`docs/container-workflows.md` for the exact workflow and deployment boundaries
and `docs/railway-environments.md` for how a green run becomes a deploy.

### Cost protection

The app has no accounts and no paid tier, so nothing gates the Gemini calls
that cost money except server-side limits. Before going live:

- Set `ALLOWED_ORIGINS` to your real frontend origin(s) — never leave it as
  `*` in production. The backend logs a startup warning if it detects a
  distributed deployment (`REDIS_URL` set) still running with `*`.
- Set `DEVICE_TOKEN_SECRET` on the API and worker; the API refuses to start
  in distributed mode without it while free runs are enabled.
- Tune `RATE_LIMIT_PER_HOUR`, `FREE_RUNS_PER_DEVICE`, `FREE_RUNS_PER_IP` and
  `DAILY_RUN_CAP` to what you're willing to spend per hour/day at your
  Gemini model's per-request price.
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

## Contributing

See `CONTRIBUTING.md`. Short version: branch from `dev`, run the checks CI
runs, keep the layering, update the `docs/` reference for anything you
touch, plain commit messages with no attribution trailers.

## License

[GNU AGPL-3.0](LICENSE). If you run a modified version of this project as a
network service, you must make your modified source available to that
service's users — see the license text for the exact terms.
