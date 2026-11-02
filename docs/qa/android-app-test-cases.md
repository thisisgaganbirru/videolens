# Android app test cases

The full manual test suite for the **installed Android app**: the real bundled
APK (static export inside the APK), never live reload from the dev server. Each
case has an ID, steps and the expected result; report every case as
PASS / FAIL / BLOCKED / N/A.

Related docs: `first-run.md`, `share-intake.md`, `free-runs.md`, `results-view.md`,
`run-history.md`, `run-status-pipeline.md`, `android-update-check.md`,
`app-shell-layout.md`, `byok-api-key.md`, `legal-offline-routes.md`.

## Environment

| Item | Value |
|---|---|
| Device | emulator-5554 (record API level and WebView version: `adb shell dumpsys package com.google.android.webview \| findstr versionName`) |
| Build | `npm run android:sync` → `gradlew assembleDebug` → `adb install -r`. Record the commit SHA and versionName. |
| Backend | local, `:8000`, started without `--reload`; reached via `adb reverse tcp:8000 tcp:8000` |
| Live reload | **off**: the synced `assets/capacitor.config.json` has no `server` key |
| Test link | `https://www.instagram.com/reel/DY2POdZonwq/` |
| Test file | a 10–20 s MP4 pushed to `/sdcard/Download/` (`ffmpeg -f lavfi -i testsrc=duration=15:size=720x1280:rate=30 -f lavfi -i sine=duration=15 -shortest test-15s.mp4`), plus an MP3 and an unsupported `.txt` |
| Screenshots | `C:\Users\birru\AppData\Local\Temp\qa2\<case-id>-<slug>.png` |

### Real-run budget

Real runs spend Gemini quota, so the suite plans exactly **two** real runs,
which also use up the device's free runs:

1. **R1**: link run (case RUN-01).
2. **R2**: file run (case RUN-02).

Free runs then reach 0, so FREE-03/04 cover the used-up state. If the counter
starts at **3** (the bundled app's `https://localhost` origin has fresh storage,
so a new device token), add **R3**: the 12 s MP3 through Browse files (case
RUN-02b). It also covers the audio path (no thumbnail, audio poster in History).
Any other starting value: report it and ask the lead before deviating. **Never** enter a real API key; BYOK cases
that need one are marked *owner-assisted*.

### Defect report format

`ID · title · severity (BLOCKER / MAJOR / MINOR / COSMETIC) · steps · expected ·
actual · screenshot · light/dark · portrait/landscape`. Mark anything you
couldn't verify as a question, not a fact.

## 1. Install and launch

| ID | Steps | Expected |
|---|---|---|
| INS-01 | Install over the existing debug build (`adb install -r`). | Installs as an update with no signature error. Survival of History and settings is tested by a **second** `-r` install of the same bundled build at the end (the first bundled install changes the origin from the dev server to `https://localhost`, so earlier data is not expected to carry over). |
| INS-02 | Check the synced config. | `assets/capacitor.config.json` has no `server` key. |
| INS-03 | Launcher icon on the home screen. | Record what it shows (currently the stock Capacitor icon; the owner's decision is pending, so this is not a defect). |
| LCH-01 | Force-stop, then cold launch from the launcher, **light** system theme. | The native launch screen shows the VideoLens ring-and-dot mark on paper `#F6F4EE`. No blue Capacitor "X" and no full-bleed image. |
| LCH-02 | Same, **dark** system theme. | Mark on the dark paper colour. No white flash. |
| LCH-03 | Watch the launch → web Splash hand-off (screen-record if possible: `adb shell screenrecord`). | Same colour throughout and no visible jump. Record whether there's a grey/blank gap and how long. |
| LCH-04 | Warm launch (Home, then reopen). | No launch screen and no web Splash replay; returns to the same screen. |
| LCH-05 | Cold launch from the launcher. | Lands on **/app** (the tool), **never** on the marketing landing page. |
| LCH-06 | Cold launch with no backend running (stop nothing; instead remove `adb reverse tcp:8000` temporarily). | The app still opens. Banner and capability show a clear "can't reach the server" state, with no crash and no blank screen. Restore the reverse afterwards. |

## 2. First run: Splash and Welcome

| ID | Steps | Expected |
|---|---|---|
| FRS-01 | `adb shell pm clear <appId>`, then launch from the launcher. | Web Splash, then the Welcome screen appears **after** the Splash, never on top of it. |
| FRS-02 | Dismiss Welcome with its primary button. | Goes to Analyze. |
| FRS-03 | Force-stop and cold launch. | **No** Welcome. |
| FRS-04 | Reboot the emulator (`adb reboot`), then launch. | **No** Welcome; History and theme are kept. |
| FRS-05 | `pm clear`, then launch **by sharing a link** into the app (SHR-02 method). | No Welcome; the link is in the field. A later launcher launch shows Welcome once. |
| FRS-06 | Welcome secondary button (if present). | Goes to its tab, and Welcome is remembered as seen. |
| FRS-07 | With Welcome open, press Android Back. | Behaves per the back rules: Welcome closes or the app stays put, and there's no navigation underneath. Record what happens. |

## 3. Shell and navigation

| ID | Steps | Expected |
|---|---|---|
| NAV-01 | Look at the bottom tab bar (Analyze, History, More). | Pinned to the bottom of the screen above the gesture/nav bar. |
| NAV-02 | Scroll a long page (a result's Transcript, a long History). | The tab bar **stays pinned**: it never floats mid-page or scrolls with content, and the content's last line isn't hidden behind it. |
| NAV-03 | Switch tabs. | The active tab is highlighted, and each tab keeps its own state (a result stays open under Analyze). |
| NAV-04 | Open More. | A sheet opens with Settings/Theme, API key, Version log, Privacy, Terms, and Update check if present. |
| NAV-05 | No footer and no top web nav anywhere in the app (portrait). | App chrome only. |
| NAV-06 | Status bar and nav bar in light theme. | Dark icons on a light bar, readable. |
| NAV-07 | Status bar and nav bar in dark theme. | Light icons, readable. Known limitation: on WebView < 140 the bar may stay white; record the WebView version and mark it KNOWN, not FAIL, if that's the case. |

## 4. Android Back button

| ID | Steps | Expected |
|---|---|---|
| BCK-01 | Open the More sheet, then Back. | The sheet closes; you stay on the tab. |
| BCK-02 | Analyze, then History, then Back. | Returns to Analyze. |
| BCK-03 | Open a run from History, then Back. | Returns to History. |
| BCK-04 | At the root (Analyze, nothing open), Back. | The app exits (goes to background), with no blank page and no landing page. |
| BCK-05 | Open Privacy from More, then Back. | Returns to the app, with no exit and no landing page. |

## 5. Intake form

| ID | Steps | Expected |
|---|---|---|
| INT-01 | Tap "Analyze link" with the field empty. | Error "Paste a link to analyze." and the field is focused. |
| INT-02 | Type `notaurl`, then submit. | Valid-URL error; no request is sent. |
| INT-03 | Untick terms, paste the link, then submit. | Terms error; Browse files is disabled. |
| INT-04 | Tap the field. | The keyboard opens and the field and Analyze button **stay visible above the keyboard**. |
| INT-05 | Rotate with the keyboard open. | The field is still visible and the layout doesn't break. |
| INT-06 | Browse files, then pick the `.txt` (if the picker allows it). | "Only MP3, MP4, and MOV files are supported." |
| INT-07 | Terms checkbox persistence: tick, then force-stop and relaunch. | Still ticked. |
| INT-08 | Terms links (Terms, Privacy). | Open the in-app pages; Back returns. |
| INT-09 | Touch device copy. | The drop zone says "Add an audio or video file", not "Drop". |

## 6. Free runs and API key

| ID | Steps | Expected |
|---|---|---|
| FREE-01 | Open Analyze before any run. | The banner shows "N free runs left" (record N; should be 2). |
| FREE-02 | After RUN-01. | The banner decrements by 1. |
| FREE-03 | After RUN-02, with 0 left. | The used-up state shows: banner with "Add key", Analyze/Browse disabled, and the link field still editable. |
| FREE-04 | In the used-up state, paste the link and tap Analyze. | Nothing is submitted; the banner/CTA explains why. |
| FREE-05 | Kill and relaunch. | The counter value is kept (it's server-side per device token). |
| KEY-01 | More → API key, then enter the dummy `invalid-test-key`, then save. | Saved state shown, and the free-runs banner hides or changes per design. **Don't submit a run with it.** |
| KEY-02 | Clear the key. | Returns to the free-runs state. |
| KEY-03 | *Owner-assisted*: a real key, then a run. | BYOK run works while free runs are 0. Skip unless the owner does it. |

## 7. Runs

| ID | Steps | Expected |
|---|---|---|
| RUN-01 (R1) | Paste the test link, then Analyze. | Stages advance Downloading → Normalizing → Uploading → Analyzing → result. Record each stage's timing. |
| RUN-02 (R2) | Browse files, then `test-15s.mp4`. | "Checking…" then "Sending…", stages, and a result. The duration is read client side. |
| RUN-02b (R3, only if free runs started at 3) | Browse files, then `test-12s.mp3`. | Stages and a result. No thumbnail (audio); History shows the audio placeholder, not a broken image. |
| RUN-03 | During a run, switch to History and back. | The run is still progressing; History shows it as in progress. |
| RUN-04 | During a run, Home, wait 20 s, then reopen. | Polling resumes and it reaches the result. |
| RUN-05 | When a run starts or finishes. | The page scrolls to the top on each state change. |
| RUN-06 | Expired run: open a run whose server copy is gone (e.g. restart the backend during RUN-02 **only if** R2 already finished; otherwise use any History row older than 1 h that has no stored result). | Its own title/copy, no stage list, and an "Analyze it again" button that pre-fills the link (link runs). |
| RUN-07 | Double-tap Analyze fast. | Exactly one run is created (check the banner only decrements by 1). |
| RUN-08 | "Analyze another file" after a result. | Form with an **empty** link field; terms stay ticked. |

## 8. Result view

| ID | Steps | Expected |
|---|---|---|
| RES-01 | Tabs: TL;DR, Notes, Transcript, On-screen. | All render with content; switching is instant. |
| RES-02 | Transcript search and the Timestamps toggle. | Search highlights or filters; the toggle shows or hides times. |
| RES-03 | Source card (link run). | Platform badge, Original post link, author, caption with Show more, stats, date. |
| RES-04 | Source card (file run). | File name/duration shown; no broken link fields. |
| RES-05 | Copy. | Check icon feedback; the clipboard holds the expected text (record whether it's the tab or all). |
| RES-06 | Share. | The Android share sheet sends the **full markdown document**, not only the active tab. |
| RES-07 | Download .md. | A file is saved, or a save/share prompt appears. Find it in Files/Downloads, open it and check it's the full markdown. **Was a MAJOR fail before.** |
| RES-08 | Original post link. | Opens externally (browser/Instagram), not inside the app WebView. Back returns to the app. |
| RES-09 | Long content. | Nothing is hidden under the tab bar at the bottom. |

## 9. History

| ID | Steps | Expected |
|---|---|---|
| HIS-01 | After R1 and R2. | Both cards: portrait poster (link) / frame poster (file), platform badge, duration, title, "Today, h:mm". |
| HIS-02 | Open each card. | The full result renders. |
| HIS-03 | Search and sort (if present). | Filter and order work. |
| HIS-04 | Delete or clear a row (if present). | Confirms first; the row is removed. **Don't clear all.** |
| HIS-05 | Airplane mode on, then open both cards. | The full results render from local storage. |
| HIS-06 | Airplane mode on, cold launch. | The app opens (bundled assets) with History usable; the banner/capability shows offline, not a crash. |
| HIS-07 | Airplane mode on, submit a link. | A clear offline/cannot-reach error inside the card; no stuck spinner. Turn airplane mode off afterwards. |

## 10. Share into the app

| ID | Steps | Expected |
|---|---|---|
| SHR-01 | App in background; share the link from Chrome into VideoLens. | The app comes forward on Analyze with the link in the field. No auto-submit. |
| SHR-02 | App killed; share the link. | Cold start, then the link in the field. No Welcome. |
| SHR-03 | Share while a result is open. | Returns to a fresh intake with the new link. |
| SHR-04 | Share plain text that isn't a URL. | Handled gracefully (empty field or validation error), no crash. |

## 11. Theme

| ID | Steps | Expected |
|---|---|---|
| THM-01 | In-app theme Light / Dark / System. | Applies immediately to every screen. |
| THM-02 | Set Dark in-app, then cold launch. | Dark from the first paint, with no light flash, on every route including Privacy/Terms. |
| THM-03 | Theme System, then change the system dark mode while the app is open. | Follows the system. |

## 12. Orientation and layout

| ID | Steps | Expected |
|---|---|---|
| ORI-01 | Landscape on Analyze, a result, History and More. | Still the **app shell** (bottom tab bar or compact app nav), **not** the desktop site with a footer. Nothing is cut off; it scrolls where needed. |
| ORI-02 | Rotate during a run. | The run keeps going and the state is kept. |
| ORI-03 | Font size Largest (Settings → Display). | Text wraps; there's no overlapping and buttons stay tappable. |
| ORI-04 | No horizontal scroll on any screen. | Pass. |

## 13. More sheet pages

| ID | Steps | Expected |
|---|---|---|
| MOR-01 | Version log. | Loads entries (or a clear offline message). |
| MOR-02 | Update check (native only). | A sensible state for a local build (no newer build, or a clear message); no crash. |
| MOR-03 | Privacy and Terms. | Render inside the app with app chrome; Back returns. |

## 14. Stability

| ID | Steps | Expected |
|---|---|---|
| STB-01 | `adb logcat` during the whole session (filter: `chromium`, `Capacitor`, `AndroidRuntime`). | No FATAL EXCEPTION. List any `Uncaught` JS errors with the screen they occurred on. |
| STB-02 | Background the app for 2 minutes during idle, then reopen. | Resumes; no reload loop. |
| STB-03 | Low memory: open several other apps, then return. | Restores to a usable state (state loss acceptable; a crash isn't). |

## Changelog

- 2026-11-01 · videolens-ff (lead) · First version of the full Android app test suite, for the bundled-APK QA pass after the Phase 5 refinement fixes.
