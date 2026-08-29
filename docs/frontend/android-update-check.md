# Native Android update check

Since this app isn't distributed through Play Store, nothing else checks for updates automatically — this does a lightweight version of it on native Android only.

**Files**
- `frontend/application/useUpdateCheck.ts` — fetches on mount, exposes `{ update }`.
- `frontend/infrastructure/updateCheck.ts` — `GithubUpdateChecker`, implements `UpdateChecker`.
- `frontend/components/UpdateBanner.tsx` — renders nothing if `update` is null, otherwise a dismissible-by-nature banner (no explicit dismiss — it just won't reappear until a newer build exists) linking to the release.

**No-ops everywhere except native Android**: `checkForUpdate()` returns `null` immediately unless `Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android"` — so on web (and any future iOS build) this is silently inert.

**Flow**: reads the installed app's `versionCode` via `@capacitor/app`'s `App.getInfo()`, fetches `${NEXT_PUBLIC_WEB_BASE_URL}/version.json` from the **deployed web app**, and compares its `versionCode` against the installed build. Only shows the banner if the manifest's version is strictly newer.

**Why not GitHub's API — this was a real, silent bug.** Until 2026-08-16 this
fetched `api.github.com/repos/.../releases` and then the release's `version.json`
asset. **The repo is private**, so the unauthenticated call always 404s, and
`if (!res.ok) return null` is indistinguishable from "no update available" — so
the banner never appeared once, on any build, and nothing anywhere reported an
error. A token cannot live in client-side JS, so the API is simply not
reachable from the app. This is the identical constraint that had already moved
the Releases tab onto a static file (`infrastructure/versionLogGateway.ts`);
the update checker was left behind on the old path.

**Why an absolute URL to the deployed web app, not a relative `/version.json`.**
`public/` ships *inside* the APK, so a relative path reads the copy frozen into
that build, which by definition can never describe a build newer than itself.
The manifest has to come from somewhere that keeps moving — the deployed web
app, which CI updates on every `dev` push. The origin is compiled in at build
time (`NEXT_PUBLIC_WEB_BASE_URL`, passed by `reusable-android-checks.yml`); when
it is unset `checkForUpdate()` no-ops rather than falling back to the frozen
local copy, and the release path fails CI if it is missing.

**CORS**: the app's origin is the Capacitor WebView (`https://localhost`), so
the read is cross-origin. `next.config.mjs` sets
`Access-Control-Allow-Origin: *` on `/version.json` only — public release
metadata, no user data. It is a plain GET, so it is a CORS "simple request" and
never preflighted. The header block is spread in conditionally because
`headers()` needs a server and the Capacitor build is `output: "export"`.

**Why a separate JSON manifest instead of parsing the release tag**: so the app doesn't depend on the tag-naming scheme (`dev-v{name}-build{n}`) staying stable — see `.github/workflows/android-development-build.yml`, which writes this file (and the identically-shaped release asset) on every `dev` push.

**Design status — extrapolated, needs review.** The Terminal mockup never drew
this banner. It's now a flat `--color-paper-2` band with a hairline below,
square, no shadow. It carries **`shrink-0`**, which matters: it sits directly
inside `.viewport` (`app/layout.tsx`), a `flex-direction: column` container, so
without it the banner compresses and the measured one-viewport frame below it
is wrong. Touch sizing (`min-h-14` on the band, `min-h-11` on the link) is
preserved.

**Known issues**

- Entirely best-effort by design — any failure anywhere in the chain (`fetch`
  failure, missing manifest, malformed JSON) is caught and treated as "no update
  available" rather than surfaced. That's intentional (never block the app over
  an update check), but it is exactly what hid the private-repo 404 above for
  every build up to `build11`. The CI guard in `reusable-android-checks.yml`
  (fails the release build when `web_base_url` is empty) is the compensating
  control: it cannot detect a *wrong* URL, only a missing one.
- **One manual install is still needed to escape it.** Builds up to `build11`
  have no `NEXT_PUBLIC_WEB_BASE_URL` compiled in, so they no-op forever and can
  never announce their own successor. The first build carrying this fix has to
  be installed by hand; from then on each build can announce the next.
- The Releases **tab** has a related but separate staleness problem on Android:
  `versionLogGateway.ts` reads a relative `/releases.json`, which on a device is
  the copy inside the APK, so the tab lists releases only up to the installed
  build. Not addressed here — it is cosmetic (the tab is a changelog, not a
  mechanism) where the update check was load-bearing.

**Tests**: none (see `run-analysis-hook.md`).

## Changelog

- 2026-08-15 · frontend agent · ported UpdateBanner; added shrink-0 so it cannot compress the measured viewport frame
- 2026-08-15 · main session · updated the manifest producer reference after Android dev automation was separated from CI
- 2026-08-15 · main session · updated the manifest producer path to the descriptive workflow naming convention
- 2026-08-16 · main session · fixed the update banner never appearing on any build: the checker called GitHub's releases API, which 404s unauthenticated on this private repo, and the 404 was swallowed as "no update". Repointed it at `${NEXT_PUBLIC_WEB_BASE_URL}/version.json` on the deployed web app (absolute, because the APK's own `public/` copy is frozen at build time), had CI write and commit that file next to `releases.json`, added the `Access-Control-Allow-Origin` header the Capacitor origin needs, and made the release build fail when `web_base_url` is missing. User-reported: no update prompt, had to uninstall and reinstall to get a new build
