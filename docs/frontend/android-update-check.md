# Native Android update check

Since this app isn't distributed through Play Store, nothing else checks for updates automatically — this does a lightweight version of it on native Android only.

**Files**
- `frontend/application/useUpdateCheck.ts` — fetches on mount, exposes `{ update }`.
- `frontend/infrastructure/updateCheck.ts` — `ApiUpdateChecker`, implements `UpdateChecker`.
- `frontend/components/UpdatePrompt.tsx` — renders nothing if `update` is null (or while the splash / first-run Welcome is up), otherwise a centred modal dialog linking to the release, with a "Later" that remembers the build. Was `UpdateBanner.tsx`, a band at the top, until refinement 10; see "Update prompt (refinement 10)".

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

**Design status — superseded by refinement 10 (popup), kept for history.** The Terminal mockup never drew
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

## Local live-reload on the emulator

> **Superseded for QA (2026-11-02):** Android QA runs on the real bundled APK only; use the next section. Kept for previewing a change by hand.

For previewing a change on an emulator without a CI build. Only a **locally built** APK can load a plain-http dev URL; CI APKs never can.

- **Ports**: run `adb reverse tcp:3005 tcp:3005` and `adb reverse tcp:8000 tcp:8000`. Backend CORS allows `localhost:3005` but not `10.0.2.2:3005`, and the app calls the API at `localhost:8000`. Re-run both after any adb, emulator or dev-server restart.
- **Dev URL**: after `cap sync`, set `server = { url: 'http://localhost:3005', cleartext: true }` in the generated, gitignored `frontend/android/app/src/main/assets/capacitor.config.json`. `frontend/capacitor.config.ts` stays untouched.
- **Cleartext flag**: Android still blocks plain http (`ERR_CLEARTEXT_NOT_PERMITTED`), so the local build needs `android:usesCleartextTraffic="true"` on `<application>` in `AndroidManifest.xml`. **Temporary, local builds only. Never commit it**, because CI publishes debug APKs.
- **Build**: `npx cap run android` fails on Windows (`'gradlew' is not recognized`). Use `.\gradlew.bat assembleDebug --console=plain`, then `adb install --no-streaming -r <apk>` and launch with `adb shell monkey -p ai.videolens.app -c android.intent.category.LAUNCHER 1`.
- **Screenshots**: an emulator with two displays needs `adb exec-out screencap -d <displayId> -p`, otherwise a warning is prepended to the PNG.
- **Free runs**: the local backend keeps its free-runs counter in memory, so a backend restart resets it to 3. Runs are in-process too and are lost on restart; reopening one then shows "This run expired on the server".

## Bundled debug APK against a local backend (refinement 1, #15)

Device QA now runs on the real bundled APK (origin `https://localhost`), not
live reload. That app calls the local backend at `http://localhost:8000`
through `adb reverse tcp:8000 tcp:8000`, which Android's default cleartext
policy blocks (`ERR_CLEARTEXT_NOT_PERMITTED`, target SDK 28+).

- `frontend/android/app/src/debug/AndroidManifest.xml` sets
  `android:networkSecurityConfig="@xml/network_security_config_debug"` on
  `<application>`.
- `frontend/android/app/src/debug/res/xml/network_security_config_debug.xml`:
  `base-config cleartextTrafficPermitted="false"`, and a `domain-config` that
  allows cleartext for `localhost`, `127.0.0.1` and `10.0.2.2` only.

**Release is untouched by construction**: Gradle merges `src/debug/` only into
the `debug` build type's variant. `src/main/AndroidManifest.xml` declares no
`networkSecurityConfig` (so no `tools:replace` is needed) and was not edited.
The temporary `usesCleartextTraffic` edit described above is no longer needed
for this flow.

Caveat: CI publishes **debug** APKs (see the live-reload section), so those do
carry this config. It only opens cleartext to loopback names and the emulator's
host alias, which reach nothing off the device. Mixed content is a separate
WebView rule: Chromium treats `http://localhost` / `127.0.0.1` as potentially
trustworthy, so `https://localhost` → `http://localhost:8000` is allowed;
`10.0.2.2` is not, and would still be blocked as mixed content.

## Banner design and dismissal (refinement 9) — superseded by the popup below; dismissal unchanged

`components/UpdateBanner.tsx` is now an editorial band (`.update-banner` in
`app/globals.css`): a 15px ink headline "Update available." plus an ink-2
"Version X is ready to install." (hidden below 25rem), a near-black
sentence-case "Get the update" pill, and a 44px X that dismisses it. Sideways
on a phone (`max-height: 31.25rem`) it collapses to one 45px row with the text
ellipsised. It keeps `flex-shrink: 0`, so the measured one-viewport frame
below it stays the right height.

**Dismissal remembers the build, not the banner.** `useUpdateCheck().dismiss()`
stores the offered `versionCode` through the new `UpdateDismissalStore` port
(`infrastructure/updateDismissalStore.ts`, `LocalStorageUpdateDismissalStore`,
key `videolens-update-dismissed`, try/catch on every access). The check hides
an update whose code is `<=` the stored one, so a newer build shows again.
`UpdateInfo` gained `versionCode` for this.

The link keeps `target="_blank"`: in the WebView that hands the release page to
Chrome, which is what makes the download and install prompt work.

Verified with Playwright and an emulated Capacitor bridge (`App.getInfo` build
10, release code 20): light and dark at 390x844, 915x360 and 1280x800; action
and dismiss 44x44; dismissed code stored as 20 and hidden after reload; shown
again when the release code became 21; no banner on the plain web.

## Update prompt (refinement 10)

Owner: "it should be on screen, not at the top". `components/UpdatePrompt.tsx`
replaces `UpdateBanner.tsx` (renamed; still mounted from `app/layout.tsx`).

- **What it is.** A native modal `<dialog class="update-prompt">` opened with
  `showModal()`, like the More sheet and Welcome: a centred `--color-surface`
  card (24rem max, `--radius-card`, `--shadow-floating`) on the shared
  `--color-backdrop`. Contents: a tint disc with lucide `Download`, a serif
  "Update available." (`h2`, the sheet title's 26px Newsreader), the ink-2 line
  "Version X is ready to install.", then the near-black `btn-ink btn-pill`
  "Get the update" (`target="_blank"`, unchanged) and an outlined `btn-secondary
  btn-pill` "Later". Hidden icon disc and tighter padding sideways
  (`max-height: 31.25rem`).
- **Frame.** The top layer takes it out of `.viewport`'s flow entirely, so it
  needs no `flex-shrink` and cannot move the fixed nav / content band / footer
  (measured: identical `.nav`, `.tabbar`, `main` boxes with and without it).
- **Dismissal.** Later, Escape, a backdrop tap and Android hardware back
  (`useHardwareBack` cancels the top `dialog[open]`) all call
  `useUpdateCheck().dismiss()`, the R9 per-version store (key
  `videolens-update-dismissed`); a newer `version_code` shows it again.
  "Get the update" closes it for this launch only (`close()`, nothing stored;
  deferred a tick, because an anchor removed during its own click cannot
  navigate), so an abandoned download is offered again next launch.
- **Accessibility.** Implicit `role="dialog"` from `<dialog>`, `aria-modal`,
  `aria-labelledby` (title) and `aria-describedby` (version line). Focus moves to
  "Get the update" on open; Tab/Shift+Tab cycle the two controls (the top layer
  already makes the page inert; a small keydown wrap stops focus leaving for the
  browser UI). On any close focus returns to the element that had it before
  the prompt opened; if there was none, to the visible view's `h1`/`h2` (given
  `tabindex="-1"`), else the first focusable control in the visible `main` —
  never `<body>` (device QA). All controls are 44px or taller.
- **Narrow + large text (device QA).** The old band's button covered its title
  at 320px with font scale >= 1.15. Here the actions are a wrapping flex row
  (`flex: 1 1 9.5em`, labels may wrap), so they stack full width when two do
  not fit; title and text use `overflow-wrap: anywhere`; the dialog is capped
  at the viewport less a margin and scrolls inside. Verified at 320 and 343px
  with `html { font-size: 130% }`: no overlaps, no clipped or overflowing
  button, buttons 57px tall and stacked.
  This also exposed a page-wide bug, fixed here: `html, body { min-width: 20rem }`
  grew with the root font size, so at 130% the page claimed 416px on a 320px
  screen (the nav's theme toggle and the prompt's right edge were cut off). It
  is now `min-width: 320px`.
- **Waits for first run.** `useFirstRunBusy()` (`application/useFirstRun.ts`)
  is true while the cold-start splash is up, or while Welcome is on the tool's
  own document; the prompt opens as soon as both are gone.
- **Still native-Android-only**, and inert on the web (`ApiUpdateChecker`
  unchanged).

**Design status — extrapolated, needs owner review.** No board draws this
dialog; it reuses the More sheet's surface, backdrop and title type and the
existing button styles.

Verified with `scratchpad\refine10\verify.py` (Playwright, emulated Capacitor
bridge, every `/api` call answered in the browser): light and dark at 390x844,
915x360 and 1280x800; 320/343px at font scale 1.0 and 1.3; 640x360 at 1.3;
all five close paths; focus return and trap; Welcome and splash gating; the
plain web shows nothing.

## Refinement 11 (2026-11-02) — prompt buttons and system font size

- **Labels on one line.** At 915x360 with font scale 1.3, "Get the update"
  wrapped onto two lines and both buttons grew to 72px. `.update-prompt__btn`
  is now `white-space: nowrap` and no longer `min-width: 0`, so a flex item's
  automatic minimum is the whole label: the buttons sit side by side when they
  fit (landscape at 130%: one line each, 57px) and the row wraps to stack them
  when they do not (portrait 320/343 at 130%, and a 390 phone at 100%, as in
  refinement 10). Verified in `scratchpad\refine11\verify.py`.
- **Changing the system font size no longer reloads the app.** Device QA: with
  a result open, changing Android's font size recreated the activity, so the
  WebView reloaded to the intake. `MainActivity`'s `android:configChanges` had
  the Capacitor template's list (`orientation|keyboardHidden|keyboard|
  screenSize|locale|smallestScreenSize|screenLayout|uiMode|navigation|density`,
  so `density` was already there) but not `fontScale`; it now ends
  `|density|fontScale`. Because the activity is no longer rebuilt, the WebView
  would keep its old text size (it reads the font scale into its text zoom
  only when its settings are created), so `MainActivity.onConfigurationChanged`
  now sets `webView.getSettings().setTextZoom(round(fontScale x 100))` when the
  scale changed. Not yet verified on a device: needs the APK from this
  refinement (font size change with a result open: result stays, text resizes).
  **Superseded by refinement 14 (below):** the `fontScale` entry in
  `configChanges` stays, but the scale no longer reaches the page as text zoom.
  `MainActivity.applyFontScale` is gone; text zoom is pinned to 100 and the
  scale becomes the root font-size.

## Refinement 14 (2026-11-02) — system font size as the root font-size

**Why.** Device QA run 15 (`docs/qa/android-app-test-cases.md`) found that the
refinement 13 chrome caps never held on Android. WebView text zoom (seeded from
the font scale when the WebView's settings are created, and re-applied live by
R11) multiplies font sizes *after* layout resolves them: at font 2.0,
`min(1.1875rem, 22px)` compared 19 with 22 and then rendered at 38px, `22px`
itself rendered at 44px, and the More sheet's em container queries (16em /
12.75em of a 288px fieldset) never fired, so "System" ran under the selected
pill. A desktop browser's text-size setting changes the root font size instead,
which is the model the web, the Playwright harness and the CSS all assume.

**What.** One text-size model on both platforms: on Android the system font
scale is the page's root font-size; text zoom stays at 100.

- `FontScalePlugin` (new, `frontend/android/app/src/main/java/ai/videolens/app/`)
  is a local Capacitor plugin with no JS methods, registered in
  `MainActivity.onCreate` next to `NativeThemePlugin`. Its `load()` runs inside
  Capacitor's Bridge constructor, after the WebView settings are made and before
  the app URL loads; it registers a **document-start script**
  (`WebViewCompat.addDocumentStartJavaScript`, restricted to the app origin) and
  sets `setTextZoom(100)`.
- The script (`FontScaleScript.script`, unit-tested in
  `src/test/.../FontScaleScriptTest.java`) sets `window.__videolensFontScale`
  and, when `<html>` already exists, `document.documentElement.style.fontSize =
  scale x 100 + "%"` (a percentage of the WebView's 16px default; scale 1
  clears it).
- `application/nativeFontScale.ts` adds `FONT_SCALE_INIT_SCRIPT` to the root
  layout's blocking pre-paint script: if the global is a number other than 1,
  it applies the same root font-size. This covers a document-start script that
  ran before `<html>` existed, and it runs before the body parses.
- **Live change:** `fontScale` stays in `configChanges` (R11), so the activity
  survives; Capacitor hands `onConfigurationChanged` to every plugin, and
  `FontScalePlugin.handleOnConfigurationChanged` swaps the document-start script
  for one with the new value (for later reloads and document navigations) and
  `evaluateJavascript`s the same script into the open page.
- **Fallback:** a WebView without the `DOCUMENT_START_SCRIPT` feature (older
  than about Chromium 87, only possible on an unupdated API 24-28 device), or
  one that rejects the origin, keeps the R11 behaviour: text zoom = font scale.
  Its text still follows the system setting; only the caps don't bind there.
- `frontend/android/app/build.gradle` gained `androidx.webkit:webkit`
  (`$androidxWebkitVersion`). Capacitor already ships that exact artifact, but as
  an `implementation` dependency, so the app module can't compile against it
  without declaring it. The APK contents don't change.

**Why a document-start script and not the alternatives.**
- `evaluateJavascript` on page load plus a stored value (e.g. in localStorage)
  can't be guaranteed to run before the first paint. A stored value is also
  missing on a first launch, and it can be stale after the setting changes
  while the app is closed.
- A CSS custom property would need the same delivery, plus a stylesheet rule
  that also exists on the web.
- A bridge or plugin method the page calls is async, so it lands after the
  first paint: a visible jump on every cold launch.
- A document-start script is the mechanism Capacitor itself uses to inject
  its bridge. It runs before any page script in every document, including
  `/privacy` and `/offline`, which load as their own documents. It reads the
  scale from the live `Configuration` each time, so nothing is stored.

**Checked.**
- **Capacitor (8.5) never touches text zoom.** `Bridge.initWebView` sets JS,
  DOM storage, geolocation, media, mixed content and the user agent only. Only
  the WebView's own default ties text zoom to the font scale, and
  `setTextZoom(100)` neutralises it.
- **The web is untouched.** The global is never set outside the app, so
  `<html>` gets no inline font-size and the user's browser text-size setting
  stays the root size. The harness measured 16px, and 24px under an emulated
  150% browser setting, with no inline style either way.
- **Body text scales exactly as before:** 16, 18.4, 20.8, 24 and 32px at 1.0,
  1.15, 1.3, 1.5 and 2.0. All app text is rem/em; the only px font sizes in the
  CSS are the two wordmark caps. The px caps now hold.
- **Pinch zoom:** WebView force-enables page zoom when text zoom is 130 or
  more. That no longer happens, but the app's viewport never disables zoom, so
  nothing is lost.
- **Breakpoints:** rem/em media queries resolve against the initial 16px, not
  the root, so on Android the `48rem` / `37.5rem` / `32rem` / `31.25rem`
  breakpoints are now fixed px whatever the font scale. This is the same model
  the harness used for refinement 13. Under text zoom, whether they moved was
  never measured. See the open question in the refinement 14 mem entry.

Verified in `scratchpad\refine14\verify.py` (emulates the plugin's exact
script, both with and without `<html>` at document start), plus
`scratchpad\refine14\r13_regress.py`, which re-runs the refinement 13 web
checks. Gradle `assembleDebug testDebugUnitTest` pass. **Device only:** whether
the document-start script lands before the first paint on a cold launch (no
jump), a live font change with a result open, and the run 15 measurements
re-taken.

## Changelog

- 2026-08-15 · frontend agent · ported UpdateBanner; added shrink-0 so it cannot compress the measured viewport frame
- 2026-08-15 · main session · updated the manifest producer reference after Android dev automation was separated from CI
- 2026-08-15 · main session · updated the manifest producer path to the descriptive workflow naming convention
- 2026-08-16 · main session · fixed the update banner never appearing on any build: the checker called GitHub's releases API, which 404s unauthenticated on this private repo, and the 404 was swallowed as "no update". Repointed it at `${NEXT_PUBLIC_WEB_BASE_URL}/version.json` on the deployed web app (absolute, because the APK's own `public/` copy is frozen at build time), had CI write and commit that file next to `releases.json`, added the `Access-Control-Allow-Origin` header the Capacitor origin needs, and made the release build fail when `web_base_url` is missing. User-reported: no update prompt, had to uninstall and reinstall to get a new build
- 2026-08-29 · frontend agent · repointed the checker from `${NEXT_PUBLIC_WEB_BASE_URL}/version.json` onto `GET /api/releases` (`latest.version_code`/`version_name`/`url`); `GithubUpdateChecker` → `ApiUpdateChecker`, dropped the now-unreachable unset-origin guard, and flagged the CI guard that still checks `web_base_url` instead of `api_base_url`
- 2026-11-01 · android-66 (device QA) · added the "Local live-reload on the emulator" section (adb reverse, generated-config server.url, temporary cleartext flag, screencap -d, in-memory free-runs counter)
- 2026-11-01 · frontend agent (refinement 1) · debug-only network security config (cleartext to localhost/127.0.0.1/10.0.2.2) via src/debug manifest overlay, for bundled-APK QA against a local backend
- 2026-11-02 · android-66 (device QA) · noted that the "Local live-reload on the emulator" section is superseded: device QA runs on the bundled APK only (see the next section)
- 2026-11-02 · frontend agent (refinement 9) · banner restyled to the editorial system ("Get the update" pill, 44px dismiss, one-row landscape); dismissal persists the dismissed version_code via the new UpdateDismissalStore port, so a newer build shows again
- 2026-11-02 · frontend agent (refinement 10) · the top banner became a centred modal `<dialog>` (`UpdatePrompt.tsx`, renamed from `UpdateBanner.tsx`): Later / Escape / backdrop / Android back keep the R9 per-version dismissal, Get the update closes for this launch only, focus trapped and returned (never `<body>`), waits for splash and Welcome; fixed `html, body` min-width from 20rem to 320px so font scale 1.3 no longer widens the page past a 320px screen
- 2026-11-02 · android-66 (device QA) · verified the refinement 10 popup on the bundled APK against the mock (run 12 in docs/qa/android-app-test-cases.md): layout, ordering after the Splash, all four dismissals with focus to the H1, "Get the update" storing no dismiss, the Tab trap and version_code 100000/1/null/503 all PASS; cosmetic: the label wraps in landscape at font 1.3; the emulator would not rotate the app, so landscape was emulated with `wm size 2400x1080`
- 2026-11-02 · frontend agent (refinement 11) · update prompt labels stay on one line (nowrap; buttons stack instead of wrapping text, 915x360 at 1.3); `fontScale` added to MainActivity configChanges with a live setTextZoom so a system font-size change keeps the open result
- 2026-11-02 · android-66 (device QA) · verified refinement 11 on the bundled APK (run 13 in docs/qa/android-app-test-cases.md): popup labels stay on one line in real landscape at font 1.3, light and dark; live fontScale change keeps the open result (no reload); emulator cold launch with rotation locked still comes up portrait, live rotation works
- 2026-11-02 · frontend agent (refinement 14) · system font scale now reaches the page as the root font-size (FontScalePlugin: document-start script + pre-paint head script, live via onConfigurationChanged), text zoom pinned to 100; R11 setTextZoom explanation marked superseded; text-zoom fallback for WebViews without DOCUMENT_START_SCRIPT
