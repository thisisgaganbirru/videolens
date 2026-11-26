---
paths:
  - ".github/**"
  - "docker-compose.yml"
  - "backend/Dockerfile"
  - "frontend/Dockerfile"
  - ".grype.yaml"
---

# CI, containers and release rules

Read `docs/container-workflows.md` before editing a workflow. Three
properties to preserve:

- Two jobs hold `contents: write`: the release job in
  `production-environment.yml`, and the auto-merge job in
  `dependabot-auto-merge.yml` (owner's decision, 2026-11-07; Dependabot PRs
  only, no checkout). Everything else stays `contents: read`; the Android
  steps live in a reusable so the dev gate and the release build share them
  without a write token. Do not add a third.
- `target_commitish: ${{ github.sha }}` on the release step pins the tag to
  the commit the APK was built from. It shipped broken once without it.
- `versionCode` is `git rev-list --count HEAD` with `fetch-depth: 0`, never
  `github.run_number` (per-workflow, resets, and Android refuses a lower
  code).

Also:

- The production APK is `assembleRelease` signed with the keystore in the
  `ANDROID_KEYSTORE_BASE64` / `ANDROID_KEYSTORE_PASSWORD` / `ANDROID_KEY_ALIAS`
  / `ANDROID_KEY_PASSWORD` secrets when all four exist. They are secrets of
  the GitHub `production` environment (admits `main` only), never repository
  secrets, and nothing passes them (`secrets:`): the `signing` and `sign`
  jobs in `reusable-android-checks.yml` run in `inputs.environment`, which
  only `production-environment.yml` sets; the dev lane names none, so
  `signing` is skipped there. Gradle never sees
  them: `android` builds the release APK unsigned, and the separate `sign`
  job (no checkout, no npm, no Gradle) signs it with `apksigner`. Keep the
  key out of any job that runs dependency code, and out of any job without
  `environment:`. With none it falls back
  (temporary, removed once the release key exists) to `assembleDebug` with the checked-in keystore (no `-PdevBuild`) and a
  `::warning::`; with only some it fails before Gradle. Never print them. Version values reach
  Gradle through the step environment, never `${{ }}` on the command line.
- Advisory scans (dev PRs, nightly) must finish green; production's Railway
  Wait for CI skips a deploy while any workflow on the commit is red.
- Two rulesets, one per branch (`docs/engineering-standards.md`, "Branch
  protection"). `dev` requires `dev-required` (dev lane aggregate); `main`
  requires `production-required` (production lane aggregate, which also
  needs `source-branch`: head must be `dev` or `hotfix/*` of this repo).
  Both require `pr-hygiene / Commit hygiene` from `commit-hygiene.yml`,
  which runs on every PR event including `edited`. The aggregates always
  report. Renaming either aggregate (or `pr-hygiene`) renames the check:
  change its ruleset in the same step, or that branch waits forever. `dev`'s
  ruleset must never require `production-required`.
- Both lanes call `reusable-commit-hygiene.yml` as `hygiene` (check
  `hygiene / Commit hygiene`) and feed it into their aggregate. Keep it there;
  the rules live in `scripts/commit-hygiene.sh`, and CI runs the base
  branch's copy of the script (not of the workflow files: a PR edits those
  for its own run, so `.github/` changes need the owner's review). Never add
  `edited` to a lane: that run would replace the aggregate with one that
  skipped the build. The title/description fetch must fail closed. Fixing
  a bad title re-runs only `pr-hygiene`; the lane's aggregate stays red
  until a push or a manual re-run.
- Images are deliberately unsigned (keyless Cosign writes to the public
  Rekor log). SBOM and provenance stay in-registry. Never pass a secret via
  `build-args`; `provenance: mode=max` records them. Use `secrets`.
- Runtime majors are declared in `/.python-version` and `/.nvmrc` and
  repeated once in each Dockerfile's literal `FROM image:tag@sha256 AS base`
  line (Dependabot only parses that shape). CI fails on drift. Pin the
  newest LTS major, never `latest`; majors are a manual upgrade.
- The final Dockerfile stage (`runtime` / `runner`) is rebuilt without cache
  so `apt-get upgrade` picks up new Debian fixes. Renaming a stage means
  updating both scan and publish workflows.
- Dependabot targets `dev`, never `main`.
