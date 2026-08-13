# Native Android update check

Since this app isn't distributed through Play Store, nothing else checks for updates automatically — this does a lightweight version of it on native Android only.

**Files**
- `frontend/application/useUpdateCheck.ts` — fetches on mount, exposes `{ update }`.
- `frontend/infrastructure/updateCheck.ts` — `GithubUpdateChecker`, implements `UpdateChecker`.
- `frontend/components/UpdateBanner.tsx` — renders nothing if `update` is null, otherwise a dismissible-by-nature banner (no explicit dismiss — it just won't reappear until a newer build exists) linking to the release.

**No-ops everywhere except native Android**: `checkForUpdate()` returns `null` immediately unless `Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android"` — so on web (and any future iOS build) this is silently inert.

**Flow**: reads the installed app's `versionCode` via `@capacitor/app`'s `App.getInfo()`, fetches the last 5 non-draft GitHub releases, finds the newest one carrying a `version.json` asset, downloads that manifest, and compares its `versionCode` against the installed build. Only shows the banner if the manifest's version is strictly newer.

**Why a separate JSON manifest instead of parsing the release tag**: so the app doesn't depend on the tag-naming scheme (`dev-v{name}-build{n}`) staying stable — see the comment in `.github/workflows/ci.yml`'s "Write version manifest" step, which is what produces this asset on every `dev` push.

**Known issue**: entirely best-effort by design — any failure anywhere in the chain (`fetch` failure, missing manifest, malformed JSON) is caught and treated as "no update available" rather than surfaced. That's intentional (never block the app over an update check), but means a broken CI manifest step would silently disable update notifications rather than erroring visibly.

**Tests**: none (see `run-analysis-hook.md`).
