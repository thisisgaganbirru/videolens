# Native Android update check

Since this app isn't distributed through Play Store, nothing else checks for updates automatically — this does a lightweight version of it on native Android only.

**Files**
- `frontend/application/useUpdateCheck.ts` — fetches on mount, exposes `{ update }`.
- `frontend/infrastructure/updateCheck.ts` — `ApiUpdateChecker`, implements `UpdateChecker`.
- `frontend/components/UpdateBanner.tsx` — renders nothing if `update` is null, otherwise a dismissible-by-nature banner (no explicit dismiss — it just won't reappear until a newer build exists) linking to the release.

**No-ops everywhere except native Android**: `checkForUpdate()` returns `null` immediately unless `Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android"` — so on web (and any future iOS build) this is silently inert.

**Flow**: reads the installed app's `versionCode` via `@capacitor/app`'s `App.getInfo()`, fetches `${NEXT_PUBLIC_API_BASE_URL}/api/releases` from the **backend**, and compares the response's `latest.version_code` against the installed build. Only shows the banner if that number is strictly newer. `latest` is `null` when no release tag matches `dev-v<version>-build<code>` and when the backend has no GitHub token configured; both cases mean "cannot say" and both no-op.

**Why not GitHub's API — this was a real, silent bug.** Until 2026-08-16 this
fetched `api.github.com/repos/.../releases` and then the release's `version.json`
asset. **The repo is private**, so the unauthenticated call always 404s, and
`if (!res.ok) return null` is indistinguishable from "no update available" — so
the banner never appeared once, on any build, and nothing anywhere reported an
error. A token cannot live in client-side JS, so the API is simply not
reachable from the app.

**Why the backend, and not the static `version.json` that replaced it.** The
2026-08-16 fix moved the read to CI, which wrote `version.json` onto the
deployed web app and **committed it back to `dev`**. That bot commit gated
deployments: a `GITHUB_TOKEN` push triggers no workflow, so it carried no
checks, and Railway's `Wait for CI` either deployed it ungated or refused to
deploy at all depending on whether a PR was open (`../railway-environments.md`).
Doing the GitHub read server-side in `GET /api/releases`
(`../backend/releases.md`) keeps the token on a server, removes the commit
entirely, and collapses the two static files into one endpoint the Releases tab
reads too (`release-notes.md`).

**Why an absolute URL, still.** `public/` ships *inside* the APK, so anything
this build carries locally can by definition never describe a build newer than
itself. The origin must point off-device and is compiled in at build time —
`NEXT_PUBLIC_API_BASE_URL`, which `reusable-android-checks.yml` passes to
`android:sync` (Next inlines `NEXT_PUBLIC_*` into the export). Unlike the old
`NEXT_PUBLIC_WEB_BASE_URL` there is no explicit "unset ⇒ no-op" guard, because
`infrastructure/apiBase.ts` falls back to `http://localhost:8000` rather than to
`undefined`: a misconfigured build fails its fetch and lands in the same
catch-and-return-null. Same outcome, one less branch.

**CORS**: the app's origin is the Capacitor WebView (`https://localhost`), so
the read is cross-origin — but it is now cross-origin to the **backend**, which
means it is governed by the backend's `ALLOWED_ORIGINS` rather than by a header
`next.config.mjs` sets. That is the same posture as every other API call the
Android app makes (`POST /api/runs` and the rest go through
`infrastructure/apiBase.ts` too), so it introduces no new requirement — but the
frontend-side `Access-Control-Allow-Origin: *` block still in `next.config.mjs`
for `/version.json` is now dead. It is a plain GET with a safelisted `Accept`
header, so it stays a CORS "simple request" and is never preflighted.

**Why `latest` is derived from the tag now.** The old design used a separate
JSON manifest specifically so the app wouldn't depend on the `dev-v{name}-build{n}`
tag scheme staying stable. The backend parses that tag instead — the dependency
moved to the server, where changing it is a deploy rather than a forced reinstall
of every APK in the field. See `../backend/releases.md`.

**Design status — extrapolated, needs review.** The Terminal mockup never drew
this banner. It's now a flat `--color-paper-2` band with a hairline below,
square, no shadow. It carries **`shrink-0`**, which matters: it sits directly
inside `.viewport` (`app/layout.tsx`), a `flex-direction: column` container, so
without it the banner compresses and the measured one-viewport frame below it
is wrong. Touch sizing (`min-h-14` on the band, `min-h-11` on the link) is
preserved.

**Known issues**

- Entirely best-effort by design — any failure anywhere in the chain (`fetch`
  failure, backend down, origin not allowed, `latest: null`, malformed JSON) is
  caught and treated as "no update available" rather than surfaced. That's
  intentional (never block the app over an update check), but it is exactly what
  hid the private-repo 404 above for every build up to `build11`. It now also
  hides a CORS rejection and a backend with no `GITHUB_TOKEN`, both of which
  look identical to "you are up to date" from inside the app.
- **The compensating CI guard no longer guards the right variable.**
  `reusable-android-checks.yml` fails the release build when `web_base_url` is
  empty. Since 2026-08-29 the value that actually matters is `api_base_url`;
  the old guard passes on a build whose update check can never work. Flagged,
  not changed — the workflows are outside this change's scope.
- **A second manual install is needed to escape this one.** Builds up to
  `build11` had no `NEXT_PUBLIC_WEB_BASE_URL` and no-op forever. Builds from
  `build12` to the last static-manifest build poll `/version.json` on the
  deployed frontend, which no longer exists — a 404, which this code treats as
  "no update". So those installs are stuck too, and the first build carrying
  the endpoint has to be installed by hand; from then on each build can
  announce the next.
- The Releases **tab**'s old Android staleness problem is gone as a side effect:
  `versionLogGateway.ts` no longer reads a relative `/releases.json` frozen
  inside the APK. Both consumers now read the same live endpoint.

**Tests**: none (see `run-analysis-hook.md`).

## Changelog

- 2026-08-15 · frontend agent · ported UpdateBanner; added shrink-0 so it cannot compress the measured viewport frame
- 2026-08-15 · main session · updated the manifest producer reference after Android dev automation was separated from CI
- 2026-08-15 · main session · updated the manifest producer path to the descriptive workflow naming convention
- 2026-08-16 · main session · fixed the update banner never appearing on any build: the checker called GitHub's releases API, which 404s unauthenticated on this private repo, and the 404 was swallowed as "no update". Repointed it at `${NEXT_PUBLIC_WEB_BASE_URL}/version.json` on the deployed web app (absolute, because the APK's own `public/` copy is frozen at build time), had CI write and commit that file next to `releases.json`, added the `Access-Control-Allow-Origin` header the Capacitor origin needs, and made the release build fail when `web_base_url` is missing. User-reported: no update prompt, had to uninstall and reinstall to get a new build
- 2026-08-29 · frontend agent · repointed the checker from `${NEXT_PUBLIC_WEB_BASE_URL}/version.json` onto `GET /api/releases` (`latest.version_code`/`version_name`/`url`); `GithubUpdateChecker` → `ApiUpdateChecker`, dropped the now-unreachable unset-origin guard, and flagged the CI guard that still checks `web_base_url` instead of `api_base_url`
