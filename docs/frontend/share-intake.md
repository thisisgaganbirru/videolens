# Share intake (a link handed to the app from outside it)

Two entry points, one path through the app:

- **Native Android share intent** — "Share → VideoLens AI" from Instagram, YouTube, a browser. `MainActivity` catches `ACTION_SEND` + `text/plain`.
- **PWA share target** — `app/manifest.ts`'s `share_target` block, which launches `/?share-target=1&title=…&text=…&url=…`.

**Files**
- `frontend/android/app/src/main/java/ai/videolens/app/MainActivity.java` — writes the shared text into `localStorage["videolens-shared-text"]` and dispatches a `videolens-share` window event (a WebView has no other way to hand a string to the page it is showing).
- `frontend/domain/ports.ts` — `SharedUrlSource` (`take()`, `subscribe()`).
- `frontend/infrastructure/sharedUrlSource.ts` — `WebShareUrlSource`, the only place that touches `localStorage`, the query string, and the native event.
- `frontend/application/useSharedUrl.ts` — `useSharedUrl()`, returns the latest `{ url, receivedAt }` or `null`.
- `frontend/components/HomeScreen.tsx` — reacts to a share: switch to Analyze, `reset()` the run.
- `frontend/components/UploadForm.tsx` — takes `sharedUrl` as a prop and fills the field.

## What a share does

A shared link is a request to analyze *that*, so it takes the screen over: whatever tab is showing, and whatever run is on it, gives way to a fresh intake with the link in the URL field. **It does not start the analysis** — an accidental share should not spend a run against the shared quota or the user's own Gemini key — so pressing `analyze url` is the one step left. (The terms checkbox is required before any submit anyway, and it is remembered across sessions.)

Only the first `https?://` match in the shared text is used: apps share "caption + link", rarely a bare URL.

## The bug this layout exists to prevent

Until 2026-08-21 the whole share path was a `useEffect` **inside `UploadForm`** — a component `HomeScreen` mounts only while `status === "idle"`. So a link shared while a finished result was on screen arrived with **nobody listening**: the event fired into the void, the text stayed in `localStorage`, and the app went on showing the previous video. The user's own report of it:

> after analyzing one video it shows the results, and we closed it. Now we are watching Instagram and we share another URL to the app — it's not showing the new one, it still shows the previous one. And when we do a back, then it goes to the home page, and there we can see that shared URL is being popped up.

That last part is the same defect from the other end: pressing back remounted `UploadForm`, whose mount-time read finally picked the link out of `localStorage` — one screen too late.

The listener therefore belongs to a component that is **always mounted**. `HomeScreen` is; the intake is not.

## Consumed exactly once, at three levels

A share is now destructive to what is on screen, so a *replayed* one would wipe a result the user is reading. Each carrier is drained as it is read:

- **Native.** `MainActivity` calls `intent.removeExtra(EXTRA_TEXT)` after handling it. Android re-delivers the launch intent to a re-created activity (process death, an uncovered config change), and `setIntent` keeps it around for exactly that.
- **Storage.** `takeNativeText()` removes the key on read — including when the shared text contained no URL at all. The old code only cleared it when a URL matched, so a text-only share sat there indefinitely and surfaced later as a phantom prefill.
- **Query string.** `takeQueryParams()` strips `url`/`text`/`title`/`share-target` with `history.replaceState`, keeping any `?view=` tab. Without it the params stay part of the launch URL, so every remount re-delivers the same link — and since tab switches are `pushState`, back would walk straight into it.

`receivedAt` makes each delivery a distinct object, so sharing the *same* link twice still reaches the effects downstream.

## What `reset()` had to learn (`useAnalysisRun`)

`HomeScreen` clears the old run by calling `reset()`, which exposed two things it did not actually do:

- **It left the poll running.** `reset` set `status: "idle"` but never cleared `pollRef`, so the next 3-second tick called `setStatus(run.status)` and dragged the pipeline straight back. This was already broken for the `analyze another file` link during a live run; a share just made it visible.
- **An in-flight request could clobber the new screen.** A `createRun` or `getRun` that was already on the wire resolves into a screen that has moved on. There is now a `generationRef` counter, bumped by `submit`, `openRun` and `reset`; each captures it and drops its result if it no longer matches. A run created by the abandoned submit still exists server-side and is reachable from History.

**Known issues / notes**
- `MainActivity` injects its script on a fixed `postDelayed(…, 500)`. On a warm start (`onNewIntent`) that is just a half-second of lag; on a cold start it is a guess about when the WebView is ready. It has not misfired in practice — Capacitor is already loading `https://localhost` when `onCreate` runs, so the `localStorage` write lands on the right origin and the mount-time `take()` picks it up — but it is a timer, not a handshake.
- Nothing tells the user *why* the field filled itself; the link simply appears. Considered and left alone — the user just came from a share sheet, so it is not a surprise.

**Tests**: no frontend test runner is configured (see `run-analysis-hook.md`). Verified in Chromium against `next start` with the API stubbed, 14 checks: a share over a finished result returns to the intake with the new link and no trace of the old result; nothing replays on remount; re-sharing the same link fills the field again; `share_target` params fill it and are stripped from the address; a share from the History tab switches to Analyze; and a share during a live run stops the poll and stays on the intake across two poll intervals.

## Changelog

- 2026-08-21 · main session · moved the share listener out of UploadForm into HomeScreen (via a SharedUrlSource port/adapter and useSharedUrl), made every carrier consume-once, and fixed reset() leaving its poll running
