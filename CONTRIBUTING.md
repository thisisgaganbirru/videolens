# Contributing to VideoLens AI

Thanks for considering a contribution. This project is licensed under
[AGPL-3.0](LICENSE) — by submitting a change, you agree it's released under
the same license.

## Getting set up

See `README.md`'s "Running locally" section for backend, frontend, and
Docker Compose setup — those steps are the source of truth and aren't
repeated here. `CLAUDE.md` and the per-package `ARCHITECTURE.md` files
document the clean-architecture layering (`domain` → `application` →
`infrastructure`/`interface`) both backend and frontend follow; read those
before making structural changes.

## Before opening a PR

Run the checks CI runs:

```bash
# backend
cd backend
python -m compileall -q app
python -m unittest discover -s tests

# frontend
cd frontend
npx tsc --noEmit
npm run build
npm run lint

# android (if you touched frontend/android)
npm run android:sync
cd android && ./gradlew assembleDebug testDebugUnitTest
```

## Conventions

- Follow the existing layering: new business rules go in `application/` use
  cases, new adapters go in `infrastructure/` behind the matching
  `domain/ports.py` (backend) or `domain/ports.ts` (frontend) interface. See
  "Adding something new" in `CLAUDE.md` for both stacks.
- Keep PRs scoped to one change. Update the relevant `docs/backend/` or
  `docs/frontend/` reference doc if you change a feature it describes.
- Never commit `.env` files, real API keys, cookie files, or Android signing
  keystores (the checked-in `frontend/android/debug.keystore` is the one
  intentional exception — see `.gitignore`'s comment on it).

## Reporting issues

Open a GitHub issue with reproduction steps. For anything security-sensitive
(a way to bypass rate limits, leak another caller's run, exfiltrate a BYOK
key, etc.), please don't open a public issue — see the contact details in
the in-app Privacy Policy instead.
