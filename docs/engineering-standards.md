# Engineering standards — deferred-work register

**This is not a per-feature reference doc.** Everything else under `docs/`
describes one feature and the files it touches. This one is cross-cutting: it
records the state of the repo's engineering hygiene — pinning, layering
enforcement, linting, typing, tests, CI gates — as measured on 2026-08-15,
when the ask was to hold this repo to enterprise standards rather than
lab-experiment quality.

**Nothing in here is fixed.** Not one line. The audit ran, the findings were
accepted, and the deliberate decision was to *not* act on any of it yet. The
frontend terminal redesign is mid-flight across several agents; landing a
formatter or a first `ruff --fix` pass on top of that would bury the redesign
review under mechanical churn, and the backend fixes would collide with
nothing but would still fragment attention.

**Trigger for picking this up**: the terminal-redesign frontend work landing,
together with whatever the remaining frontend agents surface. When that
happens, **re-check every finding below against live code before acting** —
line numbers especially. Some of this will have moved; two citations had
already drifted between the audit and this write-up (noted inline).

The three sections below are separated on purpose and the separation should
survive editing. A **real defect** is something wrong in the code or docs as
they stand. A **missing gate** is a check that would have caught a defect but
does not exist. A **convention merely absent** is neither — it is a thing
mature repos have that this one does not, with no evidence of harm yet. The
audit was explicit about not inflating one category into the next, and the
value of the register depends on that line holding.

---

## Real defects

### Unpinned backend dependencies

Highest priority on this list, and the only item with a live production
failure mode.

All 13 entries in `backend/requirements.txt` are bare `>=` floors — no upper
bound, no lockfile, no hashes. CI (`.github/workflows/ci.yml:21` — the audit
cited `:18`, which was the `python-version` line; corrected here) runs a plain
`pip install -r requirements.txt`, so the resolved dependency set genuinely
differs between runs.

Why this bites *here* specifically rather than as a generic best practice:
`backend/railway.worker.json` deploys the API and the worker as **separate
images built at different times**. `arq>=0.26.3` and `redis>=5.2` are the wire
between them; nothing stops the two images resolving to versions that no
longer agree on the job serialisation format, and the symptom would be
production-only. Separately, `yt-dlp>=2025.6.30` ships breaking releases
frequently and sits on the critical path of every URL run — an unpinned floor
there means a rebuild can break URL ingestion without a single line of our
code changing.

Worth noting that this is a backend-only gap: `frontend/` and `mcp/` both
commit a `package-lock.json`. The backend is the one package in the repo with
no reproducibility story.

Fix: `uv pip compile requirements.in -o requirements.txt --generate-hashes`,
with CI installing via `--require-hashes`. Blast radius: 1 file, ~60 lines.

### Backend layering invariant violated in three places

Root `CLAUDE.md` and `backend/ARCHITECTURE.md:14-16` both state that
`interface/` and `infrastructure/` never depend on each other directly and are
wired together only in `container.py`. Three verified violations:

- `backend/app/interface/api/dependencies.py:8` — imports
  `AuthNotConfiguredError` from `infrastructure.auth.jwt_verifier`
- `backend/app/interface/api/app.py:13` — imports `configure_logging` from
  `infrastructure.logging_config`
- `backend/app/interface/api/rate_limiter.py:5` — imports `settings` from
  `infrastructure.config`

The first is the substantive one. `dependencies.py` catches an exception
**defined inside an adapter** in order to choose an HTTP status. That means
swapping `JwtVerifier` for any other `TokenVerifier` implementation silently
breaks the 503 branch at `dependencies.py:19-20` — the new adapter raises its
own error type, the `except` never matches, and a misconfigured-auth
deployment starts returning 500s instead of 503s. That substitutability is the
entire reason the port exists. `domain/errors.py` is the stated home for
exceptions the interface layer is allowed to catch.

The other two are cross-cutting config and logging rather than adapters, and
are defensible on their own terms. But they leave the invariant unenforceable
*as written* — a reviewer looking at a new `infrastructure.*` import from
`interface/` has no bright line to point at, because two such imports are
already there and considered fine.

Fix: move `AuthNotConfiguredError` to `domain/errors.py`, then make the rule
mechanical rather than aspirational — ruff `flake8-tidy-imports` banned-api, or
an `import-linter` contract, running in CI.

### The rate limiter is built at import time from a module-level global

`backend/app/interface/api/rate_limiter.py:24`:

```python
limiter = Limiter(key_func=quota_key, storage_uri=settings.redis_url or "memory://", default_limits=[])
```

`backend/ARCHITECTURE.md:48-50` claims every adapter takes `Settings` in its
constructor rather than importing a global, and all 13 non-`__init__`
`infrastructure/` modules genuinely do. This is the sole exception, and it
imports the lowercase module-level instance.

It matters more than a style nit because the rate limiter is one of only two
things gating Gemini spend. Binding `storage_uri` at import time means the
Redis-versus-memory fallback — the exact branch that decides whether the limit
holds across replicas or only within one process — cannot be constructed
against a test config. `backend/tests/interface/api/test_rate_limiter.py`
exists, but it can only reach the pure key-derivation functions above the
`Limiter` construction; the storage decision is untestable by construction.

Fix: a `build_limiter(settings: Settings) -> Limiter` factory called from
`container.py`. Blast radius: 3 files plus 1 test.

### `CONTRIBUTING.md` tells contributors to run a command that always fails

`CONTRIBUTING.md:30` lists `npm run lint` under a heading claiming these are
the checks CI runs. It always fails —
`Invalid project directory provided, no such directory: .../frontend/lint` —
and CI does not run it at all (the frontend job is `tsc --noEmit` + `build` +
`build:mobile`).

Root `CLAUDE.md` already documents the cause (Next 16 removed `next lint`, so
the script resolves `lint` as a directory), but `CONTRIBUTING.md` is what an
external contributor reads first, and a repo about to go public whose
documented first-run checklist fails on step three reads as unmaintained.

Worse than the `CLAUDE.md` note suggests: `frontend/package.json:26-36` has
**no `eslint` and no `eslint-config-next` dependency**, and there is no
`.eslintrc*` or `eslint.config.*` anywhere in the repo. So the
`next-lint-to-eslint-cli` codemod that `CLAUDE.md` names as the fix has nothing
to migrate *to* — ESLint has to be installed from scratch, which makes this
finding entangled with the linter gate below rather than a one-line doc edit.

### `mcp/` is documented as shipped but exists only on an unmerged branch

`git ls-files mcp` returns nothing and `.mcp.json` does not exist. Root
`CLAUDE.md` nonetheless describes `mcp/` as a repo component, points readers at
`mcp/README.md` and "the repo's own root `.mcp.json`", and gives build
commands for it.

The source is safe on `feature/mcp-server` (commits `3413510`, `c9b4bea` —
neither an ancestor of `HEAD` or `main`). What is actually in the working tree
is only gitignored leftovers: four stale `mcp/dist/*.js` files, an untracked
`mcp/node_modules/`, and two empty directories `mcp/src/` and `mcp/src/tools/`.

**Decision recorded so nobody re-raises this as a bug**: the MCP work is
*deliberately* parked on its branch and will be merged once the frontend is
properly set up and working. Until then, `CLAUDE.md`'s `mcp/` section describes
a future state, and that is intentional. Do not "fix" it by deleting the
section.

The one genuine loose end is the orphaned `mcp/dist/`. It is gitignored and
harmless to the repo, but it is stale build output that someone could run
against a backend API that has since changed. (Note: the audit cited
`mcp/tsconfig.json` in the type-strictness finding below — that file is on the
branch, not in the working tree, so that half of the claim is unverifiable
until the merge.)

---

## Missing gates

Each of these maps to a defect above. That mapping is the argument for adding
them — none is being proposed because a checklist somewhere says to.

### No linter in any of the three codebases

No `eslint` or ESLint config in `frontend/` or `mcp/`. No `ruff`, `flake8`,
`pylint`, or `mypy` in `backend/` — and **no `pyproject.toml`, `setup.cfg`, or
`.ruff.toml` at all**, so there is nowhere for Python tool config to live yet.
CI runs only `compileall` + `unittest` + `tsc`.

This is the gate that would have caught the layering violations.

Fix: ruff with `select = ["E","F","I","TID","UP","B"]` plus a banned-api rule
encoding the layering invariant; ESLint 9 flat config with
`eslint-config-next` + `eslint-plugin-import`. **The first `--fix` pass is a
large mechanical diff — defer past the redesign.**

### No type checking on the Python side

`backend/app/domain/ports.py` defines 9 structural `Protocol` interfaces,
satisfied purely by duck-typing. Nothing anywhere verifies that `GeminiEngine`
actually satisfies `AnalysisEngine`, or that any other adapter still matches
its port after a signature edit.

Drift is invisible until runtime — and `process_run.py` executes inside the arq
worker, where a `TypeError` from a mismatched signature is swallowed by the
broad handler and surfaces to the user as the generic
`"Media analysis failed. Please try again."` at `process_run.py:74`. Nobody
sees a stack trace unless they go looking in worker logs.

This is the highest-value missing gate in the backend. Fix: `mypy --strict`
scoped to `app/domain` + `app/application` first — both are pure and should be
close to clean — then widen outward.

### Zero tests in `frontend/` and `mcp/`; no coverage measurement anywhere

No test files, no test script, no test framework dependency in either.
`frontend/application/useAnalysisRun.ts` — described in
`frontend/ARCHITECTURE.md:45-47` as the core submit/poll/open-from-history/
reset state machine, and the most intricate code in the frontend — has no test
at all.

The backend's 48 tests are all unit tests against fakes
(`backend/tests/application/fakes.py`); there is **no integration test
exercising a run end to end**. Untested backend modules include
`infrastructure/byok/key_vault.py`, `interface/api/routes.py` (the entire HTTP
surface), `ai/gemini_engine.py`, `storage/s3_object_store.py`, and
`queue/job_queue.py`.

`key_vault.py` is the one that should be uncomfortable: it implements a
security-critical single-use / delete-on-read / 15-minute-TTL contract for
user-supplied Gemini keys, and that contract is currently guaranteed by
nothing but code review.

Fix: Vitest + `@testing-library/react` starting with `useAnalysisRun`;
`node:test` for `mcp`; `coverage.py` reporting (not gating) on the backend.
**Purely additive — no existing file is touched**, which is why it can land
early.

### No security scanning of any kind in CI

`.github/workflows/ci.yml` has three jobs (`backend`, `frontend`, `android`)
and no CodeQL, no `dependency-review-action`, no `npm audit` / `pip-audit`, no
secret scanning, and no `.github/dependabot.yml`.

Relevant here rather than generically because this repo handles user-supplied
API keys (BYOK), carries a deliberately checked-in `debug.keystore`, and has
`.env` files across three packages — with `CONTRIBUTING.md:45-47` relying
purely on contributor discipline to keep secrets out of commits. Pre-open-
source is the cheapest moment this will ever be to add. It also compounds with
the unpinned dependencies above: no audit *and* no pin means a compromised
transitive release lands silently on the next rebuild.

### `mcp/` has no CI job

Even once the branch merges, nothing would `tsc` or build it. The stale
`mcp/dist/` sitting in the working tree is proof it can drift unbuilt.

### Branch protection is unverified

This lives in GitHub repo settings, not in the tree, and was deliberately not
guessed at. `.github/workflows/ci.yml:3-6` triggers on `pull_request` and on
pushes to `main`/`dev`, so the checks exist to be required — but whether they
actually *block* a merge has to be confirmed from Settings → Branches by
someone with access.

One catch if it gets enabled: the `android` job holds `contents: write` and
pushes a release manifest directly to `dev`. Protection on `dev` needs a
carve-out for that bot push or the release step starts failing.

---

## Conventions merely absent

No evidence of harm from any of these yet. Listed so the decision to skip them
is a decision rather than an oversight.

- **No formatter anywhere** — no Prettier, Black, or `ruff format`. Style is
  consistent by discipline alone, and genuinely is across all 79 source files
  sampled. Adding one produces the single largest mechanical diff on this
  list; it must wait for a clean branch.

- **No `.editorconfig` and no `.gitattributes`.** The index is clean LF
  (`git ls-files --eol` → 85 files at `i/lf w/crlf`), but that depends on
  *this machine's* `core.autocrlf=true` rather than any repo-level guarantee. A
  Windows contributor with `autocrlf=false` would commit CRLF and produce
  whole-file diffs. Seven files already show `w/mixed`:
  `docs/frontend/{android-update-check,byok-api-key,release-notes,results-view,run-history,run-status-pipeline,upload-form}.md`.
  Fix: `.gitattributes` with `* text=auto eol=lf` — 1 file, no source churn,
  and safe to land early.

- **Type strictness is on but shallow.** `frontend/tsconfig.json:11` sets
  `"strict": true` (and `mcp/tsconfig.json` does too, on its branch); neither
  sets `noUncheckedIndexedAccess`, `noImplicitOverride`,
  `exactOptionalPropertyTypes`, `noUnusedLocals`, or
  `noFallthroughCasesInSwitch`. `noUncheckedIndexedAccess` is the one worth
  adding — the frontend indexes into polled run arrays and history lists — but
  it produces real null-check work in exactly the files the redesign is
  rewriting, so it follows the redesign.

- **No `SECURITY.md`, `CODEOWNERS`, PR template, issue templates, or
  `CHANGELOG.md`.** `CONTRIBUTING.md:51-54` routes security reports to "the
  contact details in the in-app Privacy Policy", which GitHub will not surface
  as a security policy — no "Report a vulnerability" button, no advisory
  workflow. For a repo about to go public, `SECURITY.md` is the first of these
  to add.

- **No commit-message convention.** History is already clean imperative-mood
  prose, so Conventional Commits would formalise existing practice rather than
  change it, and would enable automated changelog generation.

- **Dead-by-design preview files ship in `components/`.**
  `frontend/components/RunStatusView.preview.tsx` and
  `frontend/components/SourceCard.preview.tsx` are documented in-file as
  dev-only harnesses and nothing imports them. Next tree-shakes them so there
  is no production impact, but they are typechecked as app code with no lint
  rule or path convention keeping them out. A `components/__previews__/`
  directory or a tsconfig exclude would make the intent structural rather than
  a comment someone has to read.

---

## Landing order

The operationally useful part of this register. When the redesign lands, work
it in this order rather than top-to-bottom.

**Safe to land immediately with near-zero source churn** — the terminal
redesign touches no backend file, so none of these conflict with it:

- the `CONTRIBUTING.md` lint line
- dependency pinning
- the three layering fixes
- the `build_limiter` factory
- `.gitattributes`
- `SECURITY.md` / `CODEOWNERS` / PR + issue templates
- CodeQL + Dependabot + gitleaks
- mypy scoped to `domain/` + `application/`
- frontend tests (additive — touches no existing file)

**Must wait for a clean branch** — large mechanical diffs that would bury a
review:

- linters, especially the first `ruff --fix` / ESLint `--fix` pass
- any formatter
- `noUncheckedIndexedAccess`

**Highest value for effort, in order:**

1. **Dependency pinning** — the only item with a live production failure mode.
2. **mypy on `domain/` + `application/`** — guards 9 Protocol interfaces
   currently verified by nothing.
3. **Security scanning** — 2 files, and pre-open-source is when it is
   cheapest.
4. **The layering fixes** — makes the architecture the docs describe actually
   true.

---

## Known issues with this register

It is a snapshot taken on 2026-08-15 against `feature/terminal-redesign`, with
several frontend agents live in the tree. Frontend line numbers in particular
should be assumed stale by the time anyone acts on this. Two citations had
already drifted at write-up time and are corrected inline
(`ci.yml:18` → `:21`; `mcp/tsconfig.json` exists only on `feature/mcp-server`).
Re-verify before fixing; do not treat the line numbers as authoritative.

## Changelog

- 2026-08-15 · standards audit agent · recorded the engineering-standards audit as a deferred register; nothing fixed yet, pickup is after the terminal redesign lands
