# VideoLens AI

Upload a short video and get a transcript, on-screen text extraction, a
natural language summary, and formatted markdown notes — powered by Gemini's
multimodal video understanding, so it captures speech, on-screen text, code,
UI, and charts, not just audio.

Users upload video files directly (mp4/mov, up to 3 minutes and 200MB).
There is no URL/link scraping for Instagram, TikTok, or YouTube — that's a
deliberate scope decision, not a missing feature.

## How it works

1. Frontend uploads a video to `POST /api/jobs`, which validates format,
   size, and duration, then immediately returns `{ job_id, status: "queued" }`.
2. The backend normalizes the video with FFmpeg, uploads it to Gemini, and
   runs a combined speech + visual analysis.
3. The frontend polls `GET /api/jobs/{job_id}` until `status` is `complete`
   or `failed`.
4. On completion the job result contains `title`, `summary`, `transcript`,
   `screen_text`, and `markdown`.

Job state lives in an in-process store for V1 — no database, no persistent
video storage. Uploaded video files are deleted from disk as soon as a job
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

Requires `ffmpeg` and `ffprobe` on PATH.

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

- `POST /api/jobs` — multipart upload, field name `file`. Returns
  `{ job_id, status }` with `202 Accepted`, or a `400` with a clear error if
  the file fails format/size/duration validation before any processing
  starts. Rate limited per IP (`RATE_LIMIT_PER_HOUR`, default 10/hour).
- `GET /api/jobs/{job_id}` — returns
  `{ job_id, status, result, error }`, where `status` is one of `queued`,
  `processing`, `complete`, `failed`.

## Configuration

See `backend/.env.example` and `frontend/.env.example`. Key backend
settings: `GEMINI_API_KEY`, `GEMINI_MODEL`, `MAX_FILE_SIZE_MB`,
`MAX_DURATION_SECONDS`, `RATE_LIMIT_PER_HOUR`, `ALLOWED_ORIGINS`.

## Deployment

Both `backend/` and `frontend/` have standalone Dockerfiles suited to
Railway or Render as two separate services. Point the frontend's
`NEXT_PUBLIC_API_BASE_URL` at the deployed backend URL, and set
`ALLOWED_ORIGINS` on the backend to the deployed frontend origin.

## Out of scope for V1

No user accounts, no payments, no mobile app, no browser extension, no
search, no sharing, no Notion/Obsidian export, no persistent video storage,
no database beyond in-process job state, no link/URL scraping.
