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

### Native splash (Android)

No `@capacitor/splash-screen` plugin is installed (no match in `package.json`
or `capacitor.config.ts`). The launch theme is `AppTheme.NoActionBarLaunch`
(`parent="Theme.SplashScreen"`, `android:background="@drawable/splash"` in
`android/app/src/main/res/values/styles.xml`). Android shows it until the
activity draws, then the WebView's first frame takes over, and the web splash
is that frame. No plugin is involved, so there is no auto-hide timer to fight.
If someone adds `@capacitor/splash-screen` later, set `launchAutoHide: true`
with a short `launchShowDuration`, or the two would stack.

**The native drawable is still Capacitor's stock placeholder**: the blue
Capacitor "X" on white, in every `drawable*/splash.png`. So today a cold start
on Android goes Capacitor logo on white → VideoLens splash on paper → app. That
is two different brands in a row and a white-to-paper colour jump. Replacing
the drawables (VideoLens mark on `#F6F4EE`, and ideally the Android 12+
`windowSplashScreen*` attributes) is a change under `frontend/android/`, which
this phase was not allowed to touch. **Owner action.**

**Not checked on a device:** whether the native exit and the web splash's first
frame line up without a flash.

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

- **Blocked `localStorage` crashes the tool before Welcome mounts.**
  `UploadForm` reads `videolens-media-terms-v1` in an effect without try/catch,
  and the throw takes down the page ("This page couldn't load"). This predates
  Phase 5d. The first-run store handles blocked storage; the page around it
  does not. Owner decision whether to fix it in `UploadForm`.
- **Cold-start native share vs Welcome.** `MainActivity` writes the shared text
  500 ms after `onCreate` (`postDelayed`). If the bundle has loaded before then,
  `pending()` reads "no share" and Welcome may start to open, then closes when
  the `videolens-share` event arrives. The link is not lost, but the user may
  see Welcome flash. Needs a device check.
- **Native and web splash hand-off timing** is unverified on a device.
- **The native launch splash is Capacitor's stock image**, not VideoLens (see
  "Native splash"). Needs new drawables under `frontend/android/`.

## Changelog

- 2026-11-01 · frontend agent (Phase 5d) · created: installed-app splash and one-time Welcome, FirstRunStore port and adapter, SharedUrlSource.pending()
