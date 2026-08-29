# Release index (`GET /api/releases`)

Serves the app's own release history so the in-app Releases tab and the Android update check can read it without a credential. Replaces two static JSON files that CI used to commit into the repository.

**Files**
- `backend/app/domain/entities.py` — `ReleaseEntry`, `LatestRelease`, `ReleaseIndex`.
- `backend/app/domain/ports.py` — `ReleaseCatalog`.
- `backend/app/infrastructure/releases/github_releases.py` — `GithubReleaseCatalog`.
- `backend/app/application/get_releases.py` — `GetReleasesUseCase`.
- `backend/app/interface/api/routes.py` — the route.
- `frontend/infrastructure/versionLogGateway.ts`, `frontend/infrastructure/updateCheck.ts` — the two consumers.

## Why it exists

The repository is private. A browser calling `api.github.com` gets a 404, and a token cannot ship in client-side JavaScript. The original workaround moved the GitHub read into CI, which then committed the answer back to `dev` as `frontend/public/releases.json` and `version.json`.

That bot commit turned out to interfere with deployment. Because GitHub does not trigger workflows for `GITHUB_TOKEN` pushes, the commit had no checks — and Railway's Wait for CI then either deployed it ungated (no PR open) or skipped the deploy entirely (PR open, checks stuck at `action_required`). See `../railway-environments.md`.

Reading GitHub server-side removes the commit. The token stays on the server, the client asks its own backend, and nothing writes to git.

## Shape

```json
{
  "releases": [{ "name": "...", "tag": "dev-v2.0.9-build24",
                 "published_at": "2026-08-29T20:10:00Z", "url": "https://..." }],
  "latest":   { "version_code": 24, "version_name": "2.0.9", "url": "https://..." }
}
```

`latest` is derived from the tag, not the release name: `dev-v<version>-build<code>`, where `<code>` is the Android `versionCode` an installed APK compares itself against. A release whose tag does not match is still listed but cannot answer "is there an update", and `latest` is `null` when none match.

## Behaviour worth knowing

- **Unconfigured is empty, not broken.** With no `GITHUB_TOKEN`, `fetch()` returns an empty index rather than raising — the same outcome the static file produced before CI had ever run. The Releases tab renders nothing and the update check no-ops.
- **Cached 300s.** GitHub rate limits per token, not per caller, so an uncached endpoint would let one busy page exhaust the budget for every user.
- **A failed refresh serves the last good answer.** A stale release list beats a broken tab, and an update check that briefly misses a new build simply retries.
- **Drafts are skipped.**

## Configuration

`GITHUB_TOKEN` (read access to the repo's releases) and `GITHUB_REPO` (defaults to `thisisgaganbirru/videolens`). Without the token the endpoint is inert but harmless.

## Known issues

- **APKs installed before this change lose their update check.** They poll `/version.json` on the deployed frontend, which no longer exists — a 404, which that code treats as "no update" and ignores. Those installs must be updated once by hand; every APK built from this commit onward uses the endpoint.
- The endpoint is unauthenticated, like `/api/capabilities`. It exposes only what a release page already shows publicly once the repo is public.

## Tests

- `backend/tests/infrastructure/releases/test_github_releases.py` — tag parsing, latest-selection, drafts, unparseable tags, unconfigured behaviour.
- `backend/tests/application/test_get_releases.py` — caching, refetch after expiry, serving stale on failure, and that a failure never propagates.

## Changelog
- 2026-08-29 · main session · created; replaces the CI-committed release manifest that was gating Railway deploys
- 2026-08-29 · frontend agent · switched both frontend consumers onto this endpoint (`FetchVersionLogGateway`, `ApiUpdateChecker`); see `../frontend/release-notes.md` and `../frontend/android-update-check.md`
