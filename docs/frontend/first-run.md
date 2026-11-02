# Splash and first-run Welcome (Phase 5d)

The installed app (PWA standalone or the Capacitor APK) gets two things a
browser tab never gets:

- **Splash** (`design/shots/SplashApp.png`): a short branded screen on cold start.
- **Welcome** (`design/shots/WelcomeApp.png`): a one-time intro on first launch.

Both boards are phone-app boards. In a browser tab, the landing page at `/`
already does Welcome's job, so neither appears there.

## Files

| File | Role |
|---|---|
| `frontend/domain/ports.ts` | `FirstRunStore` (`welcomeSeen`, `markWelcomeSeen`, `markWelcomeShownThisSession`, `markSplashShown`); `SharedUrlSource.pending()` |
| `frontend/infrastructure/firstRunStore.ts` | `BrowserFirstRunStore`: storage keys, every access in try/catch, in-memory fallback |
| `frontend/infrastructure/sharedUrlSource.ts` | `pending()`: is a share waiting (native key or share query params), without consuming it |
| `frontend/infrastructure/container.ts` | `firstRunStore` instance |
| `frontend/application/firstRunScripts.ts` | `SPLASH_INIT_SCRIPT`, inline and pre-paint. Not `"use client"`, because a server component inlines it |
| `frontend/application/useFirstRun.ts` | Module store (`useSyncExternalStore`), `useSplashHandOff()`, `useWelcome()` |
| `frontend/components/Splash.tsx` | The splash markup (`aria-hidden`) |
| `frontend/components/Welcome.tsx` | Modal `<dialog>` with three steps and two actions |
| `frontend/components/AppNav.tsx` | `BrandMark` exported (takes `className`) so splash and Welcome draw the same mark |
| `frontend/app/first-run.css` | Splash and Welcome styles, unlayered, imported by `app/app/page.tsx` only |
| `frontend/app/app/page.tsx` | Renders the splash script, `<Splash />`, the tool, `<Welcome />` |

Components never touch storage: they call `useFirstRun` hooks, which call the
`firstRunStore` adapter from the container.

## Storage

| Key | Where | Meaning |
|---|---|---|
| `videolens-welcome-v1` | localStorage | `"1"` once Welcome was dismissed (either button or Escape) |
| `videolens-welcome-session` | sessionStorage | Welcome was on screen this session, so a reload does not repeat it |
| `videolens-splash-session` | sessionStorage | The splash played this session |

If storage throws, the store keeps the same flags in memory. So with no
storage at all, Welcome is shown **at most once per page load**, not once per
session: nothing survives a reload. See Known issues for why that case cannot
currently be reached in practice.

## Splash

1. `SPLASH_INIT_SCRIPT` runs while the HTML parses. It sets `<html data-splash>`
   only if the shell is installed (`data-shell="app"`, or Capacitor native
   checked directly), the splash has not played this session, and
   `sessionStorage` can be read. If it cannot be read, there is no way to tell
   a cold start from a reload, and a splash on every reload is worse than none.
2. CSS shows `.splash` only under `:root[data-splash]`. Nothing paints without it.
3. `useSplashHandOff()` marks it played, then waits until 650 ms after
   navigation start (`650 - performance.now()`, never negative), sets
   `data-splash="leaving"` (200 ms opacity fade), then removes the attribute.
   A slow cold start never waits extra. Nothing waits on the network.
4. **Backstop:** `.splash` has `animation: splash-backstop 1ms linear 2s
   forwards`, which hides it at 2 s even if React never hydrates. It is a
   delay, not a duration, so the reduced-motion rule that zeroes durations
   leaves it working.
5. **Reduced motion:** the fade only exists under
   `prefers-reduced-motion: no-preference`; with `reduce` it is removed at once.

### Native splash (Android) — launch screen (refinement 1, #11)

No `@capacitor/splash-screen` plugin is installed, and `installSplashScreen()`
is not called anywhere. Capacitor's `BridgeActivity` calls
`setTheme(R.style.AppTheme_NoActionBar)` itself in `onCreate`, so the launch
theme is dropped without it.

The launch theme `AppTheme.NoActionBarLaunch` (`parent="Theme.SplashScreen"`,
core-splashscreen 1.2.0) now uses the Android 12+ splash attributes instead of
Capacitor's stock bitmap:

| Attribute | Value |
|---|---|
| `windowSplashScreenBackground` | `@color/splash_background`: `#F6F4EE` (`values/splash.xml`), `#0E100F` (`values-night/splash.xml`) |
| `windowSplashScreenAnimatedIcon` | `@drawable/splash_mark`: the web `BrandMark` (ring + dot) as a vector, 96dp across on the 288dp canvas, inside the 192dp safe circle |
| `postSplashScreenTheme` | `@style/AppTheme.NoActionBar` (only used if `installSplashScreen()` is ever called) |

Ring and dot colours are `@color/splash_ring` / `splash_dot` (ink and accent
per theme). The old `android:background="@drawable/splash"` item is gone, and
so are all 11 stock `splash.png` files (`drawable/`, `drawable-port-*`,
`drawable-land-*`); `styles.xml` was the only reference. The launcher icon
(`mipmap*/ic_launcher*`) is untouched and still Capacitor's stock icon.

The colours follow the **OS** night mode, the only thing known before the
WebView exists. A user who picked dark in the app on a light-mode phone sees a
paper launch screen, then the dark web splash. Since refinement 2 (#3) a user
who never picked a theme gets the device's theme in the app too, so the launch
screen and the first page agree for them (LCH-02/03); only an explicit in-app
choice that differs from the OS still shows the mismatch.

Below API 31 the compat library draws the same background and icon through
`Theme.SplashScreen`'s window background until `BridgeActivity` swaps the theme.

**For device QA (android-66), not checked here (no native build):**
1. Cold start in light and in dark OS mode: the mark on paper / dark paper,
   centred, not clipped by the circular mask, no Capacitor "X".
2. The hand-off to the web splash: the native mark sits dead centre, the web
   splash's mark sits a little above centre (wordmark under it), so a small
   jump is expected; there must be no white flash between them.
3. The gap between the launch theme ending and the WebView's first frame.
   *Fixed in refinement 3 (#3), see below.*

### No light flash before first paint (refinement 3, #3)

LCH-02 on the bundled APK: dark OS, a light flash between the splash and the
first paint. Two light surfaces sat in that gap: `capacitor.config.ts`
`android.backgroundColor` (`#F6F4EE`, one value, which `Bridge` applies to the
WebView inside `BridgeActivity.onCreate`), and `AppTheme.NoActionBar`'s window
background (the DayNight default). Both now follow the OS night mode:

| Where | What |
|---|---|
| `res/values/splash.xml`, `res/values-night/splash.xml` | new `@color/app_background`: `#F6F4EE` / `#0E100F` (same as `splash_background`) |
| `res/values/styles.xml` `AppTheme.NoActionBar` | `android:windowBackground` = `@color/app_background` (no `values-night/styles.xml` needed: the colour is the qualified resource) |
| `MainActivity.applyNightBackground()` | right after `super.onCreate` (same frame as the Bridge's own call, before anything draws) sets the WebView and decor-view background to `@color/app_background`; re-applied in `onConfigurationChanged`, because `uiMode` is in the manifest's `configChanges` (no recreate on a night-mode flip) |
| `capacitor.config.ts` | `backgroundColor` unchanged (`#F6F4EE`); the comment now says it is only the fallback. Light mode is pixel-identical |

It follows the OS, not the in-app stored theme (native cannot read that before
the page runs). An explicit in-app light choice on a dark phone therefore still
goes dark paper → light page, the expected, documented mismatch.
Verified: `./gradlew assembleDebug` after `npm run android:sync`. Not verified
on a device (no emulator access for this agent).

## Welcome

Shown when all of these hold, read once when the module loads:

- the shell is installed;
- the launch did not carry a link: no pending share (`sharedUrlSource.pending()`)
  and no `?view=` other than `analyze`. A shortcut to History or a share opens
  straight to what it asked for;
- `videolens-welcome-v1` is not set.

It opens only after the splash is gone (`open = welcome && !splash`), because a
modal dialog sits in the top layer and would cover the splash.

- **Start analyzing** (focused first) → `/app` Analyze. **Use my own Gemini
  key** → `/app?view=api-key`. **Escape** = Start analyzing. All three mark it
  seen.
- **A native share while it is open** (`videolens-share` event) closes it
  without marking it seen. The tool is mounted underneath the whole time, so the
  link reaches the intake. Welcome comes back on a later launch.
- It is a full-screen native `<dialog>` opened with `showModal()`: the page
  underneath is inert and focus stays inside.

### Why the board's copy changed

- The note says "a few free runs to start", not a number: the limit is server
  configuration (see `free-runs.md`).
- "Use my own Gemini key" is the board's secondary button, kept because BYOK
  is the way to keep going after the free runs.

## Measured (2026-11-01, `next build` + `next start -p 3015`, Playwright, 390×844)

Installed shell emulated with `videolens_shell=app`, and separately with a fake
Capacitor bridge.

- First run, light and dark: splash on screen (`data-splash=""`), then Welcome
  with focus on Start analyzing, no horizontal scroll. Start analyzing → `/app`,
  key set to `"1"`.
- Reload in the same session: no splash. New tab (new session) on `/`: goes to
  `/app`, splash plays, no Welcome.
- Use my own Gemini key → `/app?view=api-key`. Escape → closed and remembered.
- `/app?view=history` and `/?share-target=1&url=…` on a first launch: no
  Welcome; the share fills the field.
- Native share event while Welcome is open: Welcome closes, field filled,
  `videolens-welcome-v1` still unset.
- Browser tab (`videolens_shell=web`): no splash, no Welcome.
- `sessionStorage` throwing: no splash; Welcome shows until dismissed, then
  stays gone.
- Reduced motion: no transition on `.splash`.

## Known issues

- ~~Blocked `localStorage` crashes the tool before Welcome mounts.~~ Fixed in
  refinement 1 (#5). With both storages throwing (Playwright, emulated
  Capacitor): the tool loads, Welcome opens once, dismisses and stays closed for
  that page load, the terms box works, no page errors.
- **Cold-start native share vs Welcome.** `MainActivity` writes the shared text
  500 ms after `onCreate` (`postDelayed`). If the bundle has loaded before then,
  `pending()` reads "no share" and Welcome may start to open, then closes when
  the `videolens-share` event arrives. The link is not lost, but the user may
  see Welcome flash. Needs a device check.
- **Native and web splash hand-off timing** is unverified on a device.
- **Launch screen replaced, unverified on a device** (refinement 1, #11). See
  the QA list under "Native splash".
- **`SPLASH_INIT_SCRIPT` now lives in the root layout `<head>`** (refinement 1,
  #9) and gates itself on the path (`/app`, `/app/`, `/app.html`). Verified in
  the emulated asset server over `out/`: `/` → `/app.html`, theme kept.

## Changelog

- 2026-11-01 · frontend agent (Phase 5d) · created: installed-app splash and one-time Welcome, FirstRunStore port and adapter, SharedUrlSource.pending()
- 2026-11-01 · frontend agent (refinement 1) · Android launch screen: BrandMark vector + paper colours (light/night), postSplashScreenTheme, stock splash.png removed; splash script moved to the root head; storage-crash known issue closed
- 2026-11-02 · frontend agent (refinement 2) · noted that the device-following default theme makes the launch screen and first page agree when no theme is stored (LCH-02/03)
- 2026-11-02 · frontend agent (refinement 3) · window + WebView background follow the OS night mode (`@color/app_background`, `MainActivity.applyNightBackground`), closing the dark-launch light flash (LCH-02)
