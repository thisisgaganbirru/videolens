# Engineering standards — deferred-work register

**This is not a per-feature reference doc.** Everything else under `docs/`
describes one feature and the files it touches. This one is cross-cutting: it
records the state of the repo's engineering hygiene — pinning, layering
enforcement, linting, typing, tests, CI gates — as measured on 2026-08-15,
when the ask was to hold this repo to enterprise standards rather than
lab-experiment quality.

Two findings have now been addressed without touching the active frontend
redesign: backend dependency reproducibility and container-focused security
scanning. All other findings remain deferred. The sections below retain their
original audit detail, with resolution notes where work has landed.

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

**Resolved 2026-08-15.** Direct requirements now live in
`backend/requirements.in`; `backend/requirements.txt` is a universal, exact,
hash-verified lock. Local images and application checks install with
`--require-hashes`.

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

**Partially resolved 2026-08-15.** Reusable container checks now fail on
fixable high/critical findings, release images carry in-registry
SBOM/provenance attestations, and Dependabot covers Docker, Actions, npm, and
pip. Images are deliberately **unsigned** — keyless Cosign was removed the
same day because it emits permanently to Rekor, the public transparency log
(see `docs/container-workflows.md`). CodeQL, dependency review, and secret
scanning remain follow-up items.

That first scan run also produced its own finding, recorded below under
*Container base images are past end-of-life*.

The original finding: `.github/workflows/ci.yml` had three jobs (`backend`,
`frontend`, `android`) and no CodeQL, no `dependency-review-action`, no
`npm audit` / `pip-audit`, no secret scanning, and no
`.github/dependabot.yml`. `ci.yml` has since been deleted and replaced by a
caller/reusable workflow set (see `docs/container-workflows.md`), and
`.github/dependabot.yml` now exists — matching the "partially resolved" note
above. CodeQL, `dependency-review-action`, `npm audit` / `pip-audit`, and
secret scanning are still absent.

Relevant here rather than generically because this repo handles user-supplied
API keys (BYOK), carries a deliberately checked-in `debug.keystore`, and has
`.env` files across three packages — with `CONTRIBUTING.md:45-47` relying
purely on contributor discipline to keep secrets out of commits. Pre-open-
source is the cheapest moment this will ever be to add. It also compounds with
the unpinned dependencies above: no audit *and* no pin means a compromised
transitive release lands silently on the next rebuild.

### Container base images are past end-of-life

**Found 2026-08-15 by the first-ever Grype run, on PR #12.** Blocking: it is
the reason that PR is red. Not deferred — recorded here because it is a
version decision, not a mechanical fix.

> **Status 2026-08-15: a fix has landed in the tree, unverified.** The owner
> chose **Node 24 / Python 3.13** and the bump is applied, along with a
> structural change so this never needs eight edits again (see *What landed*
> below). **This entry stays open.** Nothing has been rebuilt or rescanned —
> the tree cannot run Docker or Gradle, so no image build, no Grype run, and
> no Capacitor sync has been executed against the new pins. Only a green
> PR #12 closes this.

Three failures, one root cause. Both pinned runtime majors are old enough that
the fixes for their high-severity CVEs exist only in later majors:

| Job | Finding |
|---|---|
| `containers / backend` | `python:3.11-slim` ships 3.11.16. Nine High CVEs against the `python` binary, fixed only in 3.13 / 3.14 / 3.15. |
| `containers / frontend` | `node:20-alpine` ships 20.20.2. Three High CVEs, fixed only in 22.23.2 / 24.18.1 / 26.5.1. |
| `android / Android` | `[fatal] The Capacitor CLI requires NodeJS >=22.0.0`. `reusable-android-checks.yml` pins Node 20. |

Two things make this worth writing down rather than just fixing:

**A digest bump cannot resolve any of it.** Dependabot's docker ecosystem
moves a pinned digest forward within the same tag — but no patched `3.11-slim`
or `20-alpine` exists to move to. The automation that looks like it covers
this does not.

**The scan gate is correctly configured**, which is why this is a real finding
and not a false one. `reusable-container-checks.yml` sets `only-fixed: true`
alongside `severity-cutoff: high`, so unfixable CVEs are already excluded.
Everything reported here has a fix available; it just lives in a later major.
Do not loosen the threshold to get green.

The Android failure is the same Node-20 decision wearing a different hat, and
it was foreseeable: the rewrite dropped CI from Node 22 to Node 20 to match
`node:20-alpine`, and that regression was knowingly left in place as
non-urgent. It was invisible until the restored Android gate actually ran.
Moving to Node 22 resolves the Android break and the frontend container CVEs
together.

Python is the larger lift: `backend/requirements.txt` was compiled with
`uv pip compile --python-version 3.11`, so a major move means recompiling the
hash-locked set and confirming every dependency has wheels for the new
version.

#### What landed

Owner decision: **Node 24, Python 3.13** — newest LTS, not the smallest
possible move. Since every one of these files had to be touched anyway, the
version chosen was the one that puts off doing this again the longest. That
became standing policy: **pin the newest LTS major, never `latest`.**

Two separable pieces of work landed together; they are described separately
below because they fail differently.

**Piece 1 — the version move.**

| What | Before | After |
|---|---|---|
| Node (all consumers) | 20 | **24** (`node:24-alpine`, Node 24.19.0, Alpine 3.24.1) |
| Python (all consumers) | 3.11 | **3.13** (`python:3.13-slim`, Python 3.13.15) |
| `backend/requirements.txt` | compiled `--python-version 3.11` | recompiled `--python-version 3.13` |

Digests were resolved live from the Docker Hub registry API, never copied from
documentation. The method was validated by resolving the two *outgoing* tags
at the same time: `node:20-alpine` and `python:3.11-slim` came back with
exactly the digests already pinned in the Dockerfiles. New images were then
read out of their config blobs rather than assumed. Node **24.19.0** clears
the 24.18.1 fix version the frontend finding named. Python **3.13.15** is
inferred to clear all nine backend CVEs — the finding listed them as fixed "in
3.13/3.14/3.15" without per-CVE patch versions, so that one is reasoning, not
verification.

**The `openssl>=3.5.7-r0` floor still holds.** This was the real risk in the
Node move, because the Alpine release underneath changes across Node majors:
`node:20-alpine` sat on Alpine 3.23, `node:24-alpine` sits on Alpine 3.24.
Alpine 3.24's `main/x86_64` APKINDEX serves `openssl 3.5.7-r0`, so
`apk add --upgrade 'openssl>=3.5.7-r0'` still resolves — but it is met
*exactly*, not exceeded. The constraint now sits on the boundary; raising it
requires confirming Alpine ships the higher version first.

**The recompile was almost a no-op, which is the good outcome.** `uv` 0.11.17
resolved all 54 packages to identical versions with identical hashes. The only
change is that `async-timeout==5.0.1 ; python_full_version < '3.11.3'` drops
out — a `redis` conditional that can no longer be selected once the floor is
3.13 — plus two `# via` comment lines shrinking (`anyio`, `starlette` need
`typing-extensions` only on older Pythons). No dependency lacked 3.13 support.
Because `--python-version` sets the resolution *floor*, the lock no longer
installs on 3.11; the CI pin moved in the same change, so the two stay
consistent.

**Piece 2 — one declaration per runtime, replacing eight.**

The upgrade itself exposed the real defect: the Node major was written in four
places and Python in four more, so a version move meant hunting through files
and the Android/frontend disagreement that caused this outage was *structurally
possible*. That is now collapsed:

- `/.nvmrc` (`24`) and `/.python-version` (`3.13`) hold the majors. Both
  workflows consume them via `node-version-file` / `python-version-file`; no
  workflow contains a version literal any more. Both inputs were verified
  present on the **exact pinned action SHAs** rather than trusted from current
  docs — `actions/setup-node@49933ea5` documents `.nvmrc` explicitly, and
  `actions/setup-python@a26af69b` documents `.python-version`. No action
  version needed bumping.
- Each Dockerfile declares its base image once, in a global `ARG` before the
  first `FROM` (`FROM ${NODE_IMAGE}` x3, `FROM ${PYTHON_IMAGE}` x2).
- Side benefit: `.nvmrc` and `.python-version` are what `nvm` and `pyenv`
  read, so local and CI runtimes can no longer silently disagree.

The digest cannot be collapsed into the version file, for two independent
reasons: it is a content hash and is not derivable from a version string, and
the Docker build context is the service subdirectory, so a repo-root file is
not in the build context at all.

**So the major is still written twice, and CI now enforces that they match.**
Two shell steps in `reusable-application-checks.yml` `sed` the major out of the
`ARG` and compare against the version file. The Python check also covers a
third copy: `backend/Dockerfile`'s `rm -rf /usr/local/lib/python3.13/ensurepip`
hardcodes the same minor, and a stale path makes that `rm -rf` a silent no-op
that leaves `ensurepip` in the runtime image after `pip uninstall`. It does not
fail the build, so nothing else would ever catch it. Both checks were tested
against deliberately drifted copies and do fire.

**Cost, accepted knowingly: Dependabot digest bumps for the two application
Dockerfiles.** Its parser matches literal `FROM image:tag@sha256:...` and
generally cannot resolve `FROM ${NODE_IMAGE}`. The `/backend` and `/frontend`
docker entries were kept rather than deleted so coverage resumes automatically
if anyone reverts to a literal `FROM`. Coverage *not* lost: the `/` docker
entry still bumps `redis`, `minio/minio`, and `minio/mc` in
`docker-compose.yml`, and `github-actions` / `npm` / `pip` are untouched. The
practical consequence to remember is that a quiet Dependabot is no longer
evidence the application base images are current.

`frontend/package.json` needed **no** change. Its `@types/node: ^22.10.0`
already described a newer Node than CI ran; with Node 24 it is a floor rather
than a mismatch, though tracking it to 24 would be tidier. There is no
`engines` field.

#### What is verified, and what is not

Verified locally: the recompiled lock installs cleanly under
`--require-hashes` on CPython 3.13.13, and all three backend CI steps pass on
it — `compileall -q app`, `unittest discover -s tests` (48 tests, OK), and the
`import app.main; import app.worker` check. A grep for stdlib modules removed
in 3.12/3.13 and for `sys.version_info` gates across `app/` and `tests/`
returned nothing.

Also verified: both drift-check steps fire correctly against deliberately
drifted copies (including the stale-`ensurepip` case), all four edited YAML
files parse, and no version literal remains in either workflow.

Not verified, and not claimable until CI runs: no image was built, no Grype
scan was re-run, and `cap sync android` was never executed against Node 24.
Docker and Gradle are both unavailable here. Specifically **the `FROM
${NODE_IMAGE}` / `FROM ${PYTHON_IMAGE}` indirection has never been through a
real build**, nor through `build-push-action`'s `call: check` with
`# check=error=true` — a global `ARG` with a fully-qualified default should
satisfy BuildKit's `InvalidDefaultArgInFrom` rule, but that is reasoning. The
local Python install was also resolved on Windows/amd64 rather than the Linux
CI target — `--universal` means one lock covers both, but only CI exercises
the Linux path.

Open question worth someone checking: keeping the now-probably-inert
`/backend` and `/frontend` docker entries in `.github/dependabot.yml` may
surface a "no manifest files found" warning in the Dependabot UI. That was
judged better than deleting the safety net, but it has not been observed
either way.

### `mcp/` has no CI job

Even once the branch merges, nothing would `tsc` or build it. The stale
`mcp/dist/` sitting in the working tree is proof it can drift unbuilt.

### Branch protection is unverified

This lives in GitHub repo settings, not in the tree, and was deliberately not
guessed at. `ci.yml` (single file, `pull_request` + push-to-`main`/`dev`
triggers) has since been deleted and replaced by a caller/reusable workflow
set that still runs application and container checks on pull requests into
`dev`/`main` and on pushes to `dev`/`main` (see `docs/container-workflows.md`),
so the checks still exist to be required — but whether they actually *block*
a merge has to be confirmed from Settings → Branches by someone with access.

One catch if it gets enabled: `android-development-build.yml` holds
`contents: write` and pushes a release manifest directly to `dev`. Protection
on `dev` needs a
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
- 2026-08-15 · main session · marked dependency locking and container security gates implemented while preserving the remaining deferred findings
- 2026-08-15 · main session · corrected the "signed with OIDC" claim (keyless Cosign was removed the same day) and added "Container base images are past end-of-life" — the blocking finding from the first Grype run on PR #12
- 2026-08-15 · stale-ref agent · corrected the three `ci.yml` references invalidated by the workflow rewrite (deleted `ci.yml` -> caller/reusable workflow set) at "No security scanning of any kind in CI" and "Branch protection is unverified"; left the historical `ci.yml:21` citation under "Unpinned backend dependencies" and the meta-note under "Known issues with this register" unchanged as defensible historical audit text
- 2026-08-15 · runtime-bump agent · recorded the Node 20->24 (newest LTS) / Python 3.11->3.13 bump under "Container base images are past end-of-life", plus the collapse from eight runtime declarations to one per runtime (`/.nvmrc`, `/.python-version`, one `ARG` per Dockerfile), the CI drift checks, the openssl floor check, and the Dependabot coverage traded away; entry deliberately left OPEN — only a green PR #12 closes it
- 2026-08-15 · git-commit agent · committed and pushed the Node 24 / Python 3.13 fix onto PR #12; the entry above stays OPEN here — closing it is a judgement call for whoever reads the CI result, not a mechanical follow-on to the push
