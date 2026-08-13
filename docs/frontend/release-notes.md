# Release notes / version log panel

Shows the "Releases" tab: a list of GitHub releases for this repo, most recent first.

**Why this is a static file, not a live GitHub API call**: the repo is
private, and GitHub's REST API 404s (not 403s) on unauthenticated requests
to a private repo's releases, to avoid leaking whether it exists. Calling
GitHub from the browser therefore always fails, and calling it from a
backend would need a token — which is both a credential to manage for
data that's just informational, and premature (this project has no
deployed backend yet). Instead, the one place in this pipeline that
already has legitimate GitHub access without any setup — the CI job that
publishes the release, using the ambient token every GitHub Actions run
gets for free — writes the result to a static file that ships with the
frontend build. The browser then does a same-origin `fetch`, no GitHub
call and no credential involved at runtime at all.

**Files**
- `frontend/public/releases.json` — the manifest itself: `{ "releases": [{ name, tag, publishedAt, url }, ...] }`, newest first, capped at 20 entries. Checked into git (starts as `{"releases": []}`) so local `npm run dev` has something to read before CI ever touches it.
- `frontend/infrastructure/versionLogGateway.ts` — `StaticVersionLogGateway`, does `fetch("/releases.json")`.
- `frontend/application/useVersionLog.ts` — fetches on mount.
- `frontend/components/panels/VersionLogPanel.tsx` — renders loading/error/empty/list states.
- `.github/workflows/ci.yml` (`android` job, "Update release manifest" / "Commit release manifest" steps) — right after "Publish dev release" creates the GitHub release, these steps prepend `{name, tag, publishedAt: now, url}` to `frontend/public/releases.json` (deduped by tag, sorted newest-first, capped at 20) and commit+push it straight to `dev` using the job's existing `contents: write` permission and the workflow's built-in `GITHUB_TOKEN` — no PAT, no new secret. The commit message ends in `[skip ci]` so GitHub doesn't start a new workflow run for it (which would otherwise loop: manifest commit → new run → "Publish dev release" fires again since it only checks `push to dev`, not "did this push change app code").

**Distinct from** `frontend/infrastructure/updateCheck.ts` (native-Android in-app update banner) — that one still calls GitHub's releases API directly from the client and hits the same private-repo 404. It fails silently by design (best-effort, never blocks the app), so the update banner has likely never fired. Not fixed as part of this change — it needs the on-device build-number comparison logic, which the static manifest doesn't carry; flagged separately for a future pass.

**Known limitation**: if two `dev` pushes race (a second push lands mid-build of the first), the manifest-commit step retries up to 3 times with a fetch+rebase, then fails loudly rather than silently dropping the entry. Not a real concern at this project's (solo, low-frequency) commit cadence.

**Tests**: none — this is a static file maintained by CI shell/Node, not application code with meaningful unit-testable logic. See `run-analysis-hook.md` for the project's general test-coverage stance on frontend gateways.
