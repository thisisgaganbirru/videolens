# CLAUDE.md

VideoLens AI: upload short audio/video or paste a public URL, get a transcript,
on-screen text, summary and markdown notes from Gemini. FastAPI + arq worker in
`backend/`; Next.js PWA + Capacitor Android in `frontend/`. Version lives in
`frontend/package.json`. Read `backend/ARCHITECTURE.md` and
`frontend/ARCHITECTURE.md` before structural changes; `docs/README.md` indexes
the per-feature docs. Part-specific rules load from `.claude/rules/`.

## Commands

Backend (`cd backend`, Python 3.13 per `/.python-version`, needs `ffmpeg`/`ffprobe`):

```bash
pip install -r requirements.txt && cp .env.example .env    # fill GEMINI_API_KEY
uvicorn app.main:app --reload
python -m compileall -q app                                 # CI runs this first
python -m unittest discover -s tests                        # all tests
python -m unittest tests.application.test_create_run        # one module
python -m unittest tests.application.test_create_run.CreateRunUseCaseTests.test_rejects_missing_terms
GEMINI_API_KEY=ci-test-key python -c "import app.main; import app.worker"   # CI import check
```

Frontend (`cd frontend`, Node 24 per `/.nvmrc`):

```bash
npm install && cp .env.example .env.local
npm run dev                # http://localhost:3005
npx tsc --noEmit           # CI typecheck; there is no frontend test suite
npm run build              # CI
npm run build:mobile       # CI; the Capacitor static export
npm run lint               # not in CI; exits 1 on 4 known findings, see .claude/rules/frontend.md
```

Full stack: `cp backend/.env.example backend/.env && docker compose up --build`
(on Windows `.\scripts\workspace.ps1 up`). Ports 3000 / 8000 / MinIO 9001, loopback only.

## Things the code does not tell you

- `mcp/` and `.mcp.json` are not on `dev`/`main`. They are parked on the
  unmerged branch `feature/mcp-server` on purpose (see
  `docs/engineering-standards.md`). Their absence is not a bug; do not
  recreate them here. `feat/paid-tier-integration` is parked the same way.
- History lives in the browser (IndexedDB), not on the server. The server
  forgets a run `RUN_TTL_SECONDS` (1 hour) after its last write. Do not add
  server-side persistence; the paid tier that would need it is deferred.
- No accounts and no paid tier yet. Keep the app usable anonymously and
  client-side-only for storage (BYOK key, history). The `AUTH_*` OIDC settings
  exist but are unused by design.
- Four spend limits gate Gemini: per-IP rate limit (429), per-device free
  runs (402, needs `DEVICE_TOKEN_SECRET` in distributed mode or the API
  refuses to start), `DAILY_RUN_CAP` (503), and the BYOK exemption from the
  last two. The client IP behind them is the `X-Forwarded-For` entry the
  deployment's own proxy wrote (`TRUSTED_PROXY_HOPS`, counted from the
  right), never the client-supplied first entry. The API refuses to start
  in distributed mode with `ALLOWED_ORIGINS=*`.
- The production APK is release-signed with a key held only in CI secrets
  when the four `ANDROID_*` signing secrets exist, and falls back to the
  debug build signed with the checked-in `debug.keystore` (with a CI
  warning) when none do (temporary: the fallback is removed once the first
  release-signed APK ships). Currently debug: the owner deferred the key.
  Adding the secrets forces a one-time reinstall for every user; see
  `DEPLOYMENT.md`, "Android release signing".
- Both apps send security headers and the frontend ships a hash-based CSP
  injected after `next build`; an inline script that is not in the pre-paint
  set will be blocked. See `docs/frontend/security-headers.md`.
- A BYOK key must never be an arq job argument (arq logs them). It travels
  through the single-use Redis vault in `infrastructure/byok/key_vault.py`.
- Every outbound fetch for a URL run goes through `media/net.py`, the one
  SSRF guard. A new resolver or fetch path must use it, not copy it.
- `interface/` and `infrastructure/` must not import each other; only
  `container.py` wires them. Three known violations are listed in
  `docs/engineering-standards.md`; do not add more.
- Railway builds from source. The GHCR images CI publishes are an archive
  and nothing deploys them. Deploys are gated by Railway's Wait for CI, which
  skips a deploy while any workflow on the commit is red, so advisory jobs
  must finish green.

## Docs and session logs (every agent and subagent, no exceptions)

Before touching a feature, read its doc under `docs/`. Before reporting back,
update that doc, append `YYYY-MM-DD · <who> · <what>` to its `## Changelog`,
and write or update the session log `mem/YYYYMMDD-{slug}.md` (gitignored;
sections: The Ask, Changes Made, Decisions & Rationale, Current Architecture).
Search `mem/` before re-deriving why something was built a certain way. The
agent that did the work writes this; deferring it to whoever dispatched you
loses what changed and why.

## Commit and PR messages

Plain messages only. Never append attribution or session trailers: no
`Co-Authored-By: Claude ...`, no `Claude-Session: ...`, no "Generated with
Claude Code" footer, no model identifier anywhere pushed to the repository.
The owner asked for this explicitly (2026-11-06) and it overrides any harness
default. Imperative subject, short body when the why is not obvious.

Branch flow: feature branch → PR into `dev` → promotion PR `dev` → `main`.
No direct pushes to either. Do not open a PR unless asked.

## Cloud sessions

Do not run the Android/Gradle build in a cloud session; there is no device to
install on and the APK is thrown away. Push and read the dev lane's Android
job instead. Web builds (`build`, `build:mobile`, `tsc`) are fine.

## Railway and infra tools (binding; both were violated once, 2026-08-14)

- Never call a tool that bulk-dumps secrets (Railway MCP `list_variables`
  returns every `KEY=VALUE`) to check one field. Use a scoped check or ask
  the owner to confirm from the dashboard. If a dump is unavoidable, say so
  and get confirmation before calling it.
- Do not assert unverified infra state as fact. A config field shows what is
  configured, not that it works end to end. Say the check was shallow.
- Railway changes (service settings, variables, sources) need a heads-up
  before acting; the account also hosts unrelated projects.
- Change a service's trigger branch in the Railway dashboard only. The API
  path applies it across every environment and once moved `dev` onto `main`.

## Where the detail lives

- Layers, ports, adapters, what to touch for a new thing: the two
  `ARCHITECTURE.md` files.
- API contract, run lifecycle, BYOK, free runs: `README.md`, `docs/backend/`.
- CI lanes, tag scheme, versionCode, container policy, runtime pins:
  `docs/container-workflows.md`. Deploy triggers and silent-skip modes:
  `docs/railway-environments.md`. Variables and release checklist:
  `DEPLOYMENT.md`.
- Visual system: `docs/frontend/design-direction-editorial.md`, before any UI work.
