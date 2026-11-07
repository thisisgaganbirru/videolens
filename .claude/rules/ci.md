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
  / `ANDROID_KEY_PASSWORD` secrets, passed explicitly by
  `production-environment.yml`. The job fails before Gradle if any is
  missing and never falls back to the debug keystore. Version values reach
  Gradle through the step environment, never `${{ }}` on the command line.
- Advisory scans (dev PRs, nightly) must finish green; Railway's Wait for CI
  skips a deploy while any workflow on the commit is red.
- Branch protection requires only the `required` job, which always reports.
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
