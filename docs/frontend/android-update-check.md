# Native Android update check

Since this app isn't distributed through Play Store, nothing else checks for updates automatically — this does a lightweight version of it on native Android only.

**Files**
- `frontend/application/useUpdateCheck.ts` — fetches on mount, exposes `{ update }`.
- `frontend/infrastructure/updateCheck.ts` — `GithubUpdateChecker`, implements `UpdateChecker`.
- `frontend/components/UpdateBanner.tsx` — renders nothing if `update` is null, otherwise a dismissible-by-nature banner (no explicit dismiss — it just won't reappear until a newer build exists) linking to the release.

**No-ops everywhere except native Android**: `checkForUpdate()` returns `null` immediately unless `Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android"` — so on web (and any future iOS build) this is silently inert.

**Flow**: reads the installed app's `versionCode` via `@capacitor/app`'s `App.getInfo()`, fetches the last 5 non-draft GitHub releases, finds the newest one carrying a `version.json` asset, downloads that manifest, and compares its `versionCode` against the installed build. Only shows the banner if the manifest's version is strictly newer.

**Why a separate JSON manifest instead of parsing the release tag**: so the app doesn't depend on the tag-naming scheme (`dev-v{name}-build{n}`) staying stable — see `.github/workflows/android-dev.yml`'s "Write version manifest" step, which produces this asset on every `dev` push.

**Design status — extrapolated, needs review.** The Terminal mockup never drew
this banner. It's now a flat `--color-paper-2` band with a hairline below,
square, no shadow. It carries **`shrink-0`**, which matters: it sits directly
inside `.viewport` (`app/layout.tsx`), a `flex-direction: column` container, so
without it the banner compresses and the measured one-viewport frame below it
is wrong. Touch sizing (`min-h-14` on the band, `min-h-11` on the link) is
preserved.

**Known issue**: entirely best-effort by design — any failure anywhere in the chain (`fetch` failure, missing manifest, malformed JSON) is caught and treated as "no update available" rather than surfaced. That's intentional (never block the app over an update check), but means a broken CI manifest step would silently disable update notifications rather than erroring visibly.

**Tests**: none (see `run-analysis-hook.md`).

## Changelog

- 2026-08-15 · frontend agent · ported UpdateBanner; added shrink-0 so it cannot compress the measured viewport frame
- 2026-08-15 · main session · updated the manifest producer reference after Android dev automation was separated from CI
