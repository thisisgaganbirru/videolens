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

Run state lives in an in-process store for V1 — no database, no persistent
media storage. Uploaded and downloaded files are deleted from disk as soon as a run
finishes, whether it succeeds or fails.

## Project layout

```
backend/     FastAPI app, FFmpeg processing, Gemini integration
frontend/    Next.js + Tailwind upload / status / results UI
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

Frontend at `http://localhost:3000`, backend at `http://localhost:8000`.

## API

- `POST /api/runs` — multipart request with exactly one field: `file` (MP3,
  MP4, or MOV) or `url` (a public HTTP(S) media URL). Returns `{ run_id,
  status }` with `202 Accepted`. Upload validation errors return immediately;
  URL download errors are reported through run status. Rate limited per IP
  (`RATE_LIMIT_PER_HOUR`, default 20/hour).
- `GET /api/runs/{run_id}` — returns
  `{ run_id, status, stage, result, error }`, where `status` is one of
  `queued`, `processing`, `complete`, `failed`, and `stage` (only set while
  `processing`) is one of `downloading`, `normalizing`,
  `uploading_to_gemini`, `analyzing`.

Completed/failed runs are swept from the in-process store after
`RUN_TTL_SECONDS` (default 1 hour) so long-running instances don't grow
memory unbounded.

## Configuration

See `backend/.env.example` and `frontend/.env.example`. Key backend
settings: `GEMINI_API_KEY`, `GEMINI_MODEL`, `MAX_FILE_SIZE_MB`,
`MAX_DURATION_SECONDS`, `RATE_LIMIT_PER_HOUR`, `RUN_TTL_SECONDS`, `FFMPEG_LOCATION`,
`ALLOWED_ORIGINS`.

## Deployment

Both `backend/` and `frontend/` have standalone Dockerfiles suited to
Railway or Render as two separate services. Point the frontend's
`NEXT_PUBLIC_API_BASE_URL` at the deployed backend URL, and set
`ALLOWED_ORIGINS` on the backend to the deployed frontend origin.

- **Render**: `render.yaml` at the repo root is a Blueprint defining both
  services — import the repo in Render and it picks it up automatically.
- **Railway**: `backend/railway.json` and `frontend/railway.json` configure
  each as a separate Railway service pointing at its own Dockerfile.

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every PR and
push to `main`/`dev`: it compiles and import-checks the backend, and runs a
full `next build` for the frontend.

## Out of scope for V1

No user accounts, no payments, no mobile app, no browser extension, no
search, no sharing, no Notion/Obsidian export, no persistent video storage,
no database beyond in-process run state.
