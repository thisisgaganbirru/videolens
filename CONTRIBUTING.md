# Contributing to VideoLens AI

Thanks for considering a contribution. This project is licensed under
[AGPL-3.0](LICENSE) — by submitting a change, you agree it's released under
the same license.

## Getting set up

See `README.md`'s "Running locally" section for backend, frontend, and
Docker Compose setup — those steps are the source of truth and aren't
repeated here. Runtimes are pinned in `.python-version` (3.13) and `.nvmrc`
(24). `CLAUDE.md` and the per-package `ARCHITECTURE.md` files document the
clean-architecture layering (`domain` → `application` →
`infrastructure`/`interface`) both backend and frontend follow; read those
before making structural changes. `docs/README.md` indexes the per-feature
reference docs; read the one for whatever you are about to touch.

## Branches

`dev` is the integration branch and `main` is production. Work on a feature
branch, open a pull request into `dev`, and let the promotion PR from `dev`
into `main` carry it to production. Neither `dev` nor `main` accepts direct
pushes; each requires the `required` CI check and an up-to-date branch. A
merge into `dev` deploys the dev environment on Railway; a merge into `main`
publishes the images and the Android release and deploys production. See
`docs/container-workflows.md` and `docs/railway-environments.md`.

## Before opening a PR

Run the checks CI runs:

```bash
# backend
cd backend
python -m compileall -q app
python -m unittest discover -s tests
GEMINI_API_KEY=ci-test-key python -c "import app.main; import app.worker"

# frontend
cd frontend
npx tsc --noEmit
npm run build
npm run build:mobile

# android (only if you touched frontend/android, and only on a machine with a device or emulator to install on)
npm run android:sync
cd android && ./gradlew assembleDebug testDebugUnitTest
```

`npm run lint` is worth running too, but it is not in CI and currently exits
non-zero on four pre-existing findings the owner has chosen to leave (see
`CLAUDE.md`); don't add new ones. CI also fails the backend job if
`backend/requirements.txt` was regenerated without `--universal` (it loses
its platform markers), and fails either job if a Dockerfile's base-image
major drifts from `.python-version` / `.nvmrc`.

A pull request into `dev` runs only the checks for what it touches, plus an
advisory container scan and, when `frontend/` changed, the Android build,
which keeps a dev-flavoured APK as a 14-day artifact you can install beside
the production app.

## Conventions

- Follow the existing layering: new business rules go in `application/` use
  cases, new adapters go in `infrastructure/` behind the matching
  `domain/ports.py` (backend) or `domain/ports.ts` (frontend) interface. See
  "Adding something new" in `CLAUDE.md` for both stacks.
- Keep PRs scoped to one change. Update the relevant `docs/backend/` or
  `docs/frontend/` reference doc if you change a feature it describes, and
  append a line to that doc's `## Changelog`.
- Plain commit messages: an imperative subject line, a short body when the
  why isn't obvious, and no attribution or session trailers of any kind.
- Never commit `.env` files, real API keys, cookie files, or Android signing
  keystores (the checked-in `frontend/android/debug.keystore` is the one
  intentional exception — see `.gitignore`'s comment on it). `mem/`,
  `design/` and `research/` are local-only and gitignored.
- `frontend/public/sw.js` is generated; edit `frontend/sw/sw.template.js`.
  `backend/requirements.txt` is generated; edit `requirements.in` and
  recompile with `uv`.

## Reporting issues

Open a GitHub issue with reproduction steps. For anything security-sensitive
(a way to bypass rate limits or the free-run allowance, leak another caller's
run, exfiltrate a BYOK key, reach an internal address through a URL run,
etc.), please don't open a public issue — see the contact details in the
in-app Privacy Policy instead.
