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
| FREE-02b | *(refund, backend ≥ e5b4842)* Note the count, then submit a link that fails at Downloading (e.g. the login-gated Instagram link). | The count returns to its pre-submit value. A relaunch may be needed to see it. |
| FREE-02c | *(refund, backend ≥ d032e59)* Note the count, then submit a public link longer than 180 s that downloads. | It is rejected by the duration cap and the count returns to its pre-submit value. No Gemini spend. |
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
| RUN-06b | *(refinement 3)* Live run, server forgets it: start a **link** run, then restart the backend (in-memory store) while it is processing. Stay on the run screen. | Within one poll (~3 s) or at the next reconnect: "This run expired" with "Analyze it again" (pre-fills the link). Never stuck on "Connection lost". The History row shows expired, not Processing. |
| RUN-06c | *(refinement 3)* Same as RUN-06b with a **file** run. | Expired view with "Choose the file again"; the History row shows expired. |
| RUN-06d | *(refinement 3)* Reopen from History a row the server has forgotten that is still marked Processing (e.g. start a run, restart the backend and then force-stop the app before the screen updates; relaunch with the backend still down so the startup check cannot reach it, then bring the backend up and tap the row). | Expired view with its actions, never the intake with a bare "Run not found."; the row turns expired. |
| RUN-06e | *(refinement 3, regression)* During a run, turn on airplane mode, wait, then turn it off. | "Connection lost" with the countdown and "Retry now" as before (not expired); with the network back the run resumes. |
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
| ORI-05 | *(refinement 3)* Portrait and landscape, at rest (no scrolling): Connection lost (airplane mode mid-run), a failed run, an expired run, History, API key, More pages. | No button, link or field sits under the dock; a tap just above the dock never hits a tab. Content scrolls inside the band between the top bar and the dock; the top bar and the dock never move. API key in landscape: the whole screen does not scroll. |

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

## 15. Refinement 4 additions

| ID | Steps | Expected |
|---|---|---|
| INT-01b | Portrait, empty link, tap Analyze. Repeat with an invalid URL (terms ticked), and in landscape. | Field focused, keyboard up, "Paste a link to analyze." (or the invalid-URL message) directly under the field and visible above the keyboard. |
| INT-03b | Valid link, terms unticked, tap Analyze. | Checkbox has a red outline and focus, message right under the terms row and visible; ticking the box clears it. |
| INT-05 (re-run) | Rotate to landscape with the keyboard open. | The focused field stays visible. |
| LCH-06b | Launch with :8000 unreachable. | Calm notice "Can't reach the server right now. You can still open past runs in History."; form usable; History link works. |
| LCH-06c | Backend back up after LCH-06b, bring the app to the front. | Notice clears. BLOCKED until the backend is restarted. |
| LCH-06d | Airplane mode on, launch. Airplane off, bring the app to the front. | "You're offline right now. …"; clears on return. |
| THM-01b | More > Theme: System / Light / Dark, System checked on a fresh install. Light + OS dark; System follows the OS live ("Following your device"); after the header toggle More shows Light or Dark; System hands control back. | No wrong-theme flash on relaunch. |
| RES-05b | Past completed run from History: Copy on each tab. Share label. | "<Tab> copied"; pastes only that tab; share reads "Share all results". |
| HIS-03b | Portrait, 360-class width, 3+ runs. | Sort select next to search; Oldest reverses runs and date groups; no sideways scroll. |

## 16. Refinement 5 additions

| ID | Steps | Expected |
|---|---|---|
| INT-01b (landscape) | Landscape, keyboard up, empty link then an invalid URL, Analyze. | The whole message is visible above the keyboard and the field is visible; Analyze may be off screen. |
| THM-01b-1 | OS dark, Light chosen, swipe away, relaunch. | Light launch screen (API 31+), light window, dark bar icons, no dark → light flash. |
| THM-01b-2 | OS light, Dark chosen, relaunch. | Dark launch screen and window, light bar icons, no light flash. |
| THM-01b-3 | Change the theme in More while it is open. | Bars flip immediately, no page reload; scroll position, the open sheet and form state are kept. |
| THM-01b-4 | Choose System, then relaunch. | Follows the OS live; a relaunch follows the OS. |
| THM-01b-5 | Upgrade: on the old build set Light with OS dark, install the new APK over it. | First launch may switch once; the second launch is light from frame one. |
| THM-01b-6 | System chosen, flip the OS theme while the app is open. | Bars and page both follow. |
| LCH-06d | Airplane on at launch, then off. | "You're offline right now. …"; airplane off clears it without a tap (it may then show the unreachable notice if the server is down). |

## 17. Refinement 6 and 7 additions

| ID | Steps | Expected |
|---|---|---|
| THM-01b-6a | OS dark, Light stored, cold launch, More > System, flip the OS to light. | `data-theme` and the bars turn light within about 1 s, no relaunch. |
| THM-01b-6b | System chosen, flip the OS dark → light → dark → light, about 2 s apart. | `data-theme` follows every flip. |
| THM-01b-6c | System chosen, press Home, flip the OS, return. | The page matches the OS on resume. |
| THM-01b-6d | Light, then Dark stored, flip the OS both ways. | The page does not change. |
| THM-01b-6e | System, Battery Saver on, OS light. | Page stays light unless the OS forces dark (emulator cannot force it). |
| INT-04b | Empty link, terms unticked, Analyze link. | "Paste a link to analyze." and "Accept the media-use terms before analysis." at once; focus on the link field. |
| INT-16 | Terms ticked, Browse files, pick a 0-byte `.mp4`. | "This file is empty. Choose another one." |
| INT-17 | Tap 45 px beside, above and below the terms checkbox, and its centre. | Each tap toggles it (44 px target). |
| HIS-08 | History holds a failed run whose error is the expired message. | Its card shows an "Expired" badge. |
| NF-01 | Open an unknown in-app path (`/nope`, `/app/zzz`) via CDP `location.href`. | Not-found page with the top bar and dock. |
| RTL-01 | Open a History run with an Arabic title and summary. | Title, summary and body render right-to-left, right-aligned. |

## 18. Refinement 8 additions

| ID | Steps | Expected |
|---|---|---|
| NF-01b | CDP `location.href` to `/nope`, `/nope/deeper`, `/app/zzz`, `/404`. | Each ends on `/404.html`, "This page doesn't exist.", top bar and dock, only "Open VideoLens"; the landing never shows, not even for a frame (screen recording). |
| NF-02 | On the not-found page tap "Open VideoLens"; then press Back. | Opens the tool (`/app`); Back returns to the previous in-app entry. |
| HOP-01 | Cold start, History/More tabs, More > Privacy, dock History from Privacy, Back, More > Terms, dock Analyze, Terms in-page Back link. | Each hop lands on the right page; Back walks the in-app history; no blank or stale frame. |
| LOG-01 | Logcat across the HOP-01 hops. | No "Unable to open asset URL … __PAGE__.txt" lines. |
| INT-18 | Terms unticked, tap Browse files (dark portrait, light portrait, dark landscape). | No picker; "Accept the media-use terms before analysis." shows; the checkbox is focused, outlined and in view. |
| INT-19 | Tick terms, Browse files, pick `test-12s.mp3`. | Submit is attempted; backend down gives "Can't reach the server. It may be offline, or your connection dropped." |

## 19. Update banner (mock `/api/releases` on :8000)

The mock returns `latest` = `{version_code 99999, version_name "9.9.9", url https://example.com/videolens-update-test}`; the installed build is versionCode 1.

| ID | Steps | Expected |
|---|---|---|
| UPD-01 | Cold launch with a newer release: portrait and landscape, light and dark. | The banner sits above the header (top 0–56 CSS px), with no overlap and no horizontal scroll; the one-viewport frame still holds. |
| UPD-02 | Read the banner's copy and styling. | "Version 9.9.9 is available." with an update button (≥44 px), readable in both themes. |
| UPD-03 | Tap the update button, then Back. | Opens externally (browser), not in the WebView; Back returns to the app with its state intact. |
| UPD-04 | Banner on every route: More sheet, History, Privacy, Terms, `/404.html`, Welcome/Splash. | Present and not overlapping the chrome on each. |
| UPD-05 | Font size Largest and a narrow width. | Copy wraps; the button stays tappable. |
| UPD-06 | No-update states: `latest` null, same or lower versionCode, 503. | No banner. |
| UPD-07 | Accessibility: TalkBack/role, focus order, label. | Announced sensibly; the button has an accessible name. |

## Run log

### 2026-11-01 · android-66 (device QA) · run 1 (bundled APK)

Build: 76d7f41 + landing.css WIP, versionName 2.1.1, versionCode 1, debug APK. Device: emulator API 35, WebView 124.0.6367.219, 1080x2400. Backend: local :8000 via `adb reverse`. Starting free runs: 3. Real runs used: R1 link, R2 mp4, R3 mp3. KEY-03 skipped (owner-assisted).

PASS: INS-01 (same-origin `-r` keeps History and theme; first install N/A, origin changed), INS-02, LCH-01, LCH-05, FRS-01/02/03/04/07, NAV-01/02/04/06, BCK-01..05, INT-02/03/04, FREE-01..03, RUN-01/02/02b/08, RES-01/06, HIS-01/02/05, SHR-01..04, THM-01..03, ORI-04, MOR-01..03, STB-01 (0 FATAL, 0 Uncaught).
KNOWN: NAV-07 (status bar icons unreadable when in-app theme differs from system theme, WebView 124).
Findings and questions are in the report sent to the lead; screenshots are in `%TEMP%\qa2\`.

Open items from this run: LCH-02/03 dark launch screen hands off to a light page when the system is dark and the in-app theme is the default light; RES-07 Download .md opens a text share sheet titled "Sharing text", no file saved; INT-01 inline message not confirmed; INT-09 lede still says "drop a file"; file runs show no file name in the result; `pm clear` resets the free-run counter to 3 (new device token).

### 2026-11-02 · android-66 (device QA) · run 2 (bundled APK, refinement 2)

Build: cc978f7 (adds @capacitor/filesystem), versionName 2.1.1, versionCode 1, debug APK. Device: emulator API 35, WebView 124.0.6367.219. Backend: lead's local :8000 via `adb reverse`; the lead restarted it three times (counter back to 3 each time). Real runs: R1 link, R2 mp4, R3 mp3, RUN-06 link (interrupted), ORI-02 link, FRS-04 link.

PASS: LCH-04/05, FRS-01..07, NAV-01..07 (NAV-07 also live and while backgrounded), BCK-01..05, INT-02/04/07/08/09, FREE-01..05, KEY-01/02, RUN-01/02/02b/03/04/07/08, RES-01..04/06/08/09, HIS-01/02/05, SHR-01..04, THM-03, ORI-01/02/04, MOR-01..03, STB-01 (no app FATAL, 0 Uncaught; the one FATAL in the crash buffer was the `uiautomator` helper), STB-02/03.
FAIL: LCH-02/03 (about 0.4 s light frame between the dark launch screen and the dark page), RUN-06 (stuck on "Connection lost", then "Run not found." from History, row stays Processing), INT-01 (message sits under the keyboard), INT-03 (checkbox not marked), INT-05 (landscape with keyboard: the focused field is hidden), RES-07 (share sheet "Sharing 1 file", no explicit save target).
PARTIAL / NOTES: LCH-06 (opens, error on submit, no proactive offline state), THM-01 (no way back to System once toggled), HIS-03 (search and filter work; sort is a native select that could not be driven), RES-05 (copies the active tab only).
N/A: HIS-04 (no delete control anywhere), KEY-03 (owner-assisted). INS-03: stock Capacitor icon. NOT RUN: INT-06, HIS-06, HIS-07 (round-1 evidence only), ORI-03 (round-1 evidence only), RUN-06b..e and ORI-05 (refinement 3).

### 2026-11-02 · android-66 (device QA) · runs 3 and 4 (bundled APK, 2a13890 then 03dd55e, backend DOWN)

Device: emulator API 35, rebuilt headless with swiftshader after the first emulator died (LCH-02/03 timings are swiftshader). Backend stopped (memory), so every real-run case is BLOCKED: RUN-05, RUN-06, 06b..e, ORI-02 retest, FREE-*, LCH-06c. Run 3 (2a13890, partial): INT-04 PASS; INT-01, INT-03, INT-05 FAIL (fixed by 03dd55e); HIS-01/02/06/07, NAV scroller, ORI-03, ORI-05 landscape, KEY-01/02 PASS.
Run 4 (03dd55e): PASS INT-01b (portrait empty and invalid), INT-03b, INT-05 (field stays visible), LCH-02/03 (luma 74 → 69/65 → 31, no light frame), LCH-06b, THM-01b (except relaunch flash), RES-05b and HIS-03b (PASS, seeded history; width was 411dp, not 360), BCK/NAV sanity, STB-01 (0 FATAL).
PARTIAL / FAIL: INT-01b landscape (message clipped under the keyboard; only about 5 px visible, the field and button are visible); LCH-06d (airplane on shows "Can't reach the server right now…", not "You're offline right now…"; possibly navigator.onLine stays true on the emulator, unconfirmed); THM-01b relaunch (Light chosen under OS dark: blank dark window about 6.7 s, then the light page; likely exaggerated by swiftshader, and status/nav bars stay dark over a light page).
Screenshots in `%TEMP%\qa3\` and `%TEMP%\qa4\`.

### 2026-11-02 · android-66 (device QA) · run 5 (bundled APK, refinement 5, 324608b, backend DOWN)

Build: 324608b installed with `-r` at 02:33:47 (NativeTheme plugin, MainActivity night mode in attachBaseContext, ACCESS_NETWORK_STATE confirmed granted). Emulator API 35, swiftshader. Evidence in `%TEMP%\qa5\`.
PASS: INT-01b landscape (empty: "Paste a link to analyze." and invalid: "Enter a valid public HTTP or HTTPS URL." fully visible above the keyboard; minor: the field's top edge and the Analyze button are partly under the header line), THM-01b-1 / THM-01b-5 (upgrade: first launch after install showed the old dark window ~7 s then light, luma 74 → 35/29 → 212; second launch light from frame one, luma 74 → 133 → 213, dark bar icons), THM-01b-2 (OS light + Dark: luma 82 → 64 → 32 → 44, no light frame), THM-01b-3 (Dark ↔ Light in More flips the bars at once; the sheet, scroll position and ticked terms stay), THM-01b-4 (System follows the OS; relaunch follows), LCH-06d ("You're offline right now. …" with airplane at launch; off → notice becomes the server-unreachable one without a tap), LCH-02/03 (System + OS dark: luma 74 → 65 → 33 → 44, no light frame), NAV/BCK sanity (back from a result goes to History, back closes the sheet, back at the Analyze root leaves the app), STB-01 (0 FATAL, 0 app crashes; only the Capacitor console error "Error injecting safe area CSS: Cannot read properties of null (reading 'style')" on launch).
FAIL (intermittent): THM-01b-6. Repro: OS dark, Light stored, cold launch (activity forced light), More > System, then flip the OS to light while the app stays open. The status/nav bars turn light but the page stays dark: `matchMedia('(prefers-color-scheme: dark)')` stays true, even after Home and back to the app; a cold relaunch fixes it. Not reproduced with live toggles only (Dark/Light/System taps) or after a cold launch under System. Screenshots `THM6-os-flip-light-8s.png`, `THM6-repro3.png`.

### 2026-11-02 · android-66 (device QA) · run 6 (bundled APK, refinements 6 and 7, afb41d8 (worktree build), backend DOWN)

Build: `refine7-debug.apk` built from the afb41d8 worktree, installed with `-r` (lastUpdateTime 03:15:54); `android:sync` was not run in the main tree. Emulator API 35, swiftshader. OS theme driven with `cmd uimode night`. Evidence in `%TEMP%\qa6\`.
PASS: THM-01b-6a (page light within 1.5 s; `matchMedia` still reports dark, which the web side now ignores), 6b (4 flips followed), 6c (correct on resume, both directions), 6d (Light and Dark stay put), THM-01b-1..4 regression (luma: System + OS dark 74 → 65 → 32 → 44; System + OS light 82 → 172 → 222; Light + OS dark light from frame one; Dark + OS light dark from frame one), INT-04b (both errors at once, focus on the link), INT-16 ("This file is empty. Choose another one."), INT-17 (taps 45 px beside, 50 px below and 62 px above the 20 px box all toggle; the whole label row is the target), HIS-08 (Expired badge on a seeded failed run), RTL-01 (Arabic title, key takeaway right-aligned, RTL), STB-01 (0 FATAL, 0 Uncaught since install).
BLOCKED: THM-01b-6e, needs physical device (emulator `low_power` doesn't force night; `settings put global low_power 1` leaves `uimode` at "no").
FAIL (MINOR, question for the lead): NF-01. On the bundled app every unknown path (`/nope`, `/nope/deeper`, `/app/zzz`) renders the landing page (title "VideoLens AI", "Turn any short video into clean notes.") with the dock, not the not-found page. Capacitor logs "Handling local request: https://localhost/nope" and serves `index.html`, so the exported 404 never loads; the address stays on the bad path.
NOTES: the safe-area console error still shows once per cold launch (2 lines since install across launches). With the terms unticked "Browse files" looks dimmed and a tap opened no picker (CDP: `disabled` true when unticked, false when ticked); question whether that is intended, since INT-04b expects the form to be submittable to show errors. `Unable to open asset URL: /app/__next.app.__PAGE__.txt?_rsc=…` appears repeatedly in logcat, also on earlier builds (RSC prefetch, no visible effect).
BLOCKED (backend stopped, memory, awaiting owner restart): RUN-*, FREE-*, ORI-02 retest, LCH-06c.

### 2026-11-02 · android-66 (device QA) · run 7 (bundled APK, refinement 8, 04a9a9c (worktree build), backend DOWN)

Build: `refine8-debug.apk` installed with `-r` (lastUpdateTime 03:45:20); `android:sync` not run in the main tree. Emulator API 35, swiftshader. Evidence in `%TEMP%\qa8\`.
PASS: NF-01b (all four paths end on `/404.html` with title "Page not found · VideoLens AI"; a 34 s screen recording of the four hops, sampled at 3 fps, shows no landing frame after any navigation; `NF_nope.png`, `sheet.png`), NF-02 ("Open VideoLens" opens `/app`; Back returns to `/404.html`), HOP-01 (`/privacy.html`, `/terms.html`, dock History/Analyze to `/app`, Back through `/privacy.html` then `/terms.html`), LOG-01 (0 "Unable to open asset URL" lines; 3 debug "Handling local request … __PAGE__.txt" lines remain, served normally), INT-18 (dark portrait, light portrait and dark landscape: no picker, terms error, checkbox focused, outlined and in view; `BRW-unticked-dark.png`, `BRW-landscape-after.png`, `BRW-light.png`), INT-19 ("Can't reach the server. It may be offline, or your connection dropped."; `BRW-submit-6s.png`), STB-01 (0 FATAL, 0 Uncaught, 0 ANR), NAV/BCK sanity (More sheet Back closes it; a fresh cold start with Back at the root leaves to the launcher).
NOTES: the Terms in-page "Back" link lands on `/app.html` rather than `/app` (same page content; two URLs for the tool, so History/Back entries may differ); the safe-area console error did not appear in this session's logcat.
BLOCKED (backend stopped, memory, awaiting owner restart): RUN-*, FREE-*, ORI-02 retest, LCH-06c. THM-01b-6e stays BLOCKED (needs physical device).

### 2026-11-02 · android-66 (device QA) · run 8 (bundled APK, 04a9a9c (worktree build), backend killed mid-attempt)

Build: unchanged from run 7 (lastUpdateTime 03:45:20). Evidence in `%TEMP%\qa9\`.
Lead GO'd the real-run cases (backend health 200 at 11:36), then reported the backend and :3005 killed for low memory. At the GO the banner read "3 free runs left" (so R3 applies) and the capability banner "Limited: link downloads."
RUN-01 attempt: link typed (`RUN01-filled.png`); no run was observed (no stage, no result) before the stop, and health was down at 11:40. The terms checkbox was unticked in the later screenshot (`after-stop.png`); I did not record whether it was ticked when I tapped Analyze, so I can't say whether the submit was blocked by the terms or by the outage. Question: is the terms tick meant to reset on a force-stop and cold launch? (Earlier runs kept it ticked.)
BLOCKED (backend killed for memory): RUN-*, FREE-*, RUN-06b..e, ORI-02 retest, LCH-06c. No result to log for any of them; no defect logged.

### 2026-11-02 · android-66 (device QA) · run 9 (bundled APK, 04a9a9c (worktree build), update banner on a mock, partial)

Build: unchanged (lastUpdateTime 03:45:20, versionCode 1). The mock on :8000 is described in section 19. Evidence in `%TEMP%\qa10\`.
PASS: UPD-01. Portrait: the banner is 0–56 px, the header 56–125, the content band 125–775, the dock 783–847, and scrollWidth equals the viewport. Landscape (915x360): banner 0–56, header 56–113, band 113–292 (only 179 px), dock 300–352. Both themes. Note: the banner takes about 16% of the landscape height.
PASS: UPD-03. ACTION_VIEW opens Chrome; Back returns to MainActivity with the same pid on `/app.html`.
UPD-02 observations:
- Copy is "Version 9.9.9 is available."; the button reads "update" in portrait and "download update" in landscape (sm+).
- The copy is 12.48 px; light rgb(58,59,66) on white, dark rgb(198,201,194) on rgb(23,26,24).
- The button is 44 px tall, with a 16 px label. Question: the label is larger than the copy; is that type-scale mismatch intended?
- No dismiss control.
PARTIAL: UPD-04. The More sheet covers the dock while the banner stays above it, dimmed by the scrim; History is fine. Privacy, Terms, `/404.html` and Welcome/Splash were not reached because the emulator went offline.
PAUSED (the mock was swapped for the real backend; resumes on a separate GO): rest of UPD-04, UPD-05, UPD-06, UPD-07.

### 2026-11-02 · android-66 (device QA) · run 10 (bundled APK, 04a9a9c (worktree build), real backend, real runs)

Build: unchanged. Emulator API 35, swiftshader, laptop restarted before the run. Backend: the lead's real :8000 via `adb reverse` (HEAD 4e2ef7e). Evidence in `%TEMP%\qa11\`. Stage times come from an in-page `fetch` hook polled through CDP, so they are accurate to the app's 3 s poll.
PASS:
- **INT-07 / terms persistence.** Starting state: unticked, key empty. Ticked → `videolens-media-terms-v3` = "accepted" → force-stop → cold launch: still ticked and still "accepted".
- **RUN-02 (R2, `test-15s.mp4`).** Sending… then POST 202, Normalizing at +4 s (about 3 s), Uploading at +7 s, Analyzing from +13 s, complete at +25 s.
- **RUN-02b (R3, `test-12s.mp3`).** Already at Analyzing by +3 s; complete at +13 s.
- **RUN-01 retry.** Link `https://www.youtube.com/watch?v=jNQXAC9IVRw` ("Me at the zoo", public, 19 s): Downloading at +3 s, Uploading at +6 s (Download and Normalize took ≤6 s together), Analyzing from +12 s, complete at +24 s.
- **170 s file (`test-170s.mp4`, 720x1280, 2.5 MB).** Normalizing about 57–60 s, Uploading about 9 s, Analyzing about 15 s, complete at +88 s. **Normalizing is the main cost on longer files.**
- **RUN-03.** History shows the in-flight file run and link run as "Processing"; the run continues when you return.
- **RUN-04 (weak).** Home for 20 s: the run completed in the background (polling never paused), and the result showed on reopen.
- **RUN-05.** The scroller goes to 0 on each state change.
- **RUN-07.** A fast double-tap sends exactly one POST.
- **RUN-08.** After a failed run and after a result: empty link field, terms still ticked.
- **ORI-02.** Rotating during Analyzing keeps the state; the run completed in landscape and the result was kept on rotating back.
- **HIS-01.** Frame poster with 0:15 for the mp4; waveform placeholder with "Audio file" and 0:12 for the mp3.
- **FREE-01..05.**
  - The count went 3 → 2 on the failed Instagram run. Policy: failures during processing are not refunded.
  - Used-up state: "You have used your free runs. Add your own key to keep going." Analyze link and Browse files are disabled; the link field stays editable. Add key opens `/app?view=api-key`, and Back returns.
  - At 0, IME Enter and a tap on Analyze send no request.
  - The used-up state is kept across a force-stop and relaunch.
- **RUN-06b.** A restart while Analyzing: one poll shows "Connection lost", then the next poll gets 404 and the expired view appears ("This run expired", "Analyze it again" fills in the link without submitting). The History row shows an Expired badge.
- **RUN-06c.** The lead restarted the backend at about +39 s, during Normalizing on `test-170s.mp4`. The app showed "Connection lost"; at +55 s a poll got 404 and the expired view appeared ("Choose the file again"). The History row shows failed/file.
- **RUN-06e** (retest; replaces the earlier BLOCKED). Cut at +12 s during Normalizing with `adb reverse --remove tcp:8000; adb reconnect`. The app showed "Connection lost / Waiting for connection" with a live countdown, "Retry now" and "Stop watching", and never showed expired. Backoff was about 4/8/16/30 s. After the reverse was restored, the run resumed and completed.
- **RUN-06d.** The lead stopped the backend at about +40 s during Normalizing, then I force-stopped the app. The row stayed "Processing".
- **LCH-06b.** A cold launch with the backend down shows "Can't reach the server right now. You can still open past runs in History."
- **LCH-06c.** The backend came up at 13:28:25 and I foregrounded the app at 13:28:37. The notice cleared within 2 s and the banner refreshed to "3 free runs left". Tapping the stale Processing row got a 404; the expired view appeared and the row turned Expired.
- **FREE-02b** (backend d032e59). Count 3 before. I submitted the Instagram link; the free-runs fetch right after the POST returned 2. The run failed at Downloading about 3 s later ("This post isn't public…"). After a cold relaunch the banner shows "3 free runs left", so the run was refunded.
- **STB-01.** No app FATAL or Uncaught errors; only system bluetooth and binder lines.

NOT EXERCISED: FREE-02c. `https://www.youtube.com/watch?v=dQw4w9WgXcQ` (3:33) failed at Downloading after about 12 s with "This link couldn't be downloaded. It may be private, deleted, or region-locked." It never reached the duration check. According to the lead, the backend log shows the download started (229 MiB, best format) and then hit "HTTP Error 403: Forbidden" partway through: YouTube throttling, not a private video. The duration-cap refund is covered by unit tests. The run was still refunded (3 → 2 → 3), which is a second FREE-02b data point. To test the cap itself, the lead needs to supply a link over 180 s that downloads.

FAIL (environment): first RUN-01 attempt with the Instagram test link: "This post isn't public - Instagram only serves it to signed-in viewers." at Downloading after 6 s. The backend has no yt-dlp cookies configured, so the suite's link was swapped for the YouTube one above.
Emulator note for RUN-06e: with airplane mode on, `navigator.onLine` goes false, but `adb reverse` traffic still flows (loopback). Removing the reverse alone leaves the keep-alive socket open. Only `adb reverse --remove tcp:8000; adb reconnect` cuts the traffic. The first attempt completed and used 1 free run.
NOTES:
- MINOR (known, covered by refinement 9): after a refunded failure the app does not re-fetch `/api/free-runs`. "Analyze another file" leads to an intake that still shows "2 free runs left" while the server already shows 3 (`FREE02c-intake-insession.png`). Only a relaunch or a resume corrects it, so the user believes the failed link cost a run. Suggested fix: re-fetch when a run reaches `failed`, or when the intake mounts.
- Known, covered by refinement 9: the failed view has no free-runs banner, so the refund is not visible at the point of failure.
- Observation: the startup reconcile did not turn the stale Processing row Expired on resume; only tapping the row did.
- MINOR: "Choose the file again" on the expired file view goes to the intake instead of opening the picker.
- COSMETIC: during an mp3 run in Analyzing, the status heading reads "Reading your video / Longer files take more time to normalize."
- COSMETIC: the source card reads "Source: Youtube, jawed" (should be "YouTube").
- Copy question: the expired view says "The server keeps a run for an hour" even when the run was lost to a restart.
- MINOR: the used-up reason appears only in the top banner; once the form is scrolled into view, the disabled button gives no inline reason.
- After a backend restart the banner keeps the stale "used your free runs" until a cold relaunch.

### 2026-11-02 · android-66 (device QA) · run 11 (refinement 9, `refine9-debug.apk` at 79d69fc, real backend)

Build: `adb install --no-streaming -r refine9-debug.apk` (lastUpdateTime 14:15:30), then `adb reverse tcp:8000 tcp:8000`. Emulator API 35. The backend was restarted on the R9 code at 14:14, which reset the free runs to 3. Evidence in `%TEMP%\qa12\`. Stage copy was logged by a CDP poller (every 0.5 s) together with the in-page fetch hook.
PASS:
- **R9-1, stage copy by stage and media.**
  - mp3: "Sending your audio for analysis", then "Listening to your audio". No audio state says "video".
  - 15 s mp4: "Preparing your video" (Normalizing, about 6 s), then "Sending your video for analysis", then "Reading your video". Complete at +23 s.
  - YouTube link: "Sending your video…", then "Reading your video".
  - Not observed, because the stage passed before the first poll: "Preparing your audio" and "Downloading the video". Both strings are in `RunStatusView.tsx` `progressCopy`.
- **R9-2.** At 0 free runs, the intake note reads "No free runs left today, so analyzing is paused. Add key to keep going." Its "Add key" opens `/app.html?view=api-key`.
- **R9-3.** "YouTube" is spelled correctly in the History filter, the row label, the source card ("Source: YouTube, jawed") and the `.md` export ("**Platform:** YouTube"). The lowercase form appears only in URLs. The export is written to `cache/exports/` and shared through the chooser.
- **R9-4.** The expired view no longer mentions "an hour". It reads "The server no longer has this run, and its result never reached this device. Nothing was wrong with the link…" (for a file: "…the file; choose it again to start over.").
- **R9-5.** The free-runs count is re-fetched when a run completes (mp3 → 2, mp4 → 0), when it fails (refunded link failures, back to 2), and when the app resumes (Home for 8 s, then brought back; returning from the file picker as well). The intake count was correct every time.
- **R9-6** (on the expired file view). With terms ticked, "Choose the file again" opens DocumentsUI `PickActivity` directly. With terms unticked, it lands on the intake with the checkbox outlined in red and "Accept the media-use terms before analysis."
- **R9-7, refund line** (the download-failure half). Both the Instagram link and the YouTube-blocked link show "This didn't use one of your free runs." The count was 2, went to 1 during the run, and went back to 2.
- **R9-8.** The Back links on Terms and Privacy (`href=/app`) and the dock's Analyze tab on both pages all land on `/app.html`.
- **R9-9.** Failed link rows created on R9 are titled "Instagram link" and "YouTube link".
- **R9-10.** `dQw4w9WgXcQ` was blocked and failed in 3 s with "You can try the same link again later, or download the video and upload the file instead." The detail line reads "The site blocked this download for now - the video itself is fine. Try again in a few minutes."
- **INT-07 regression.** Re-ticked the terms, force-stopped and cold launched: still `accepted`.

NOT EXERCISED: the other half of R9-7, that a run which reaches analysis and then fails shows no refund line. I couldn't trigger such a failure without spending a run, and the count was at 0.
NOTES:
- Tester artifact, not a defect: the "Privacy Policy" link wraps onto two lines, so a tap at the centre of its bounding box lands on the label text and toggles the terms checkbox. Each line of the link is about 46×18 css px, which is small as a tap target.
- COSMETIC: the expired view states the same thing twice: the lede, then "This run is no longer on the server, and its result never reached this device."
- COSMETIC: the `.md` export shows "**Published:** 20050424", the raw yt-dlp date.
- MINOR: the inline "Add key" in the paused note is a single text line, about 19 css px tall. The top banner's Add key button is the larger target.
- Budget: 3 free runs used (mp3, YouTube link, 15 s mp4). Both link failures were refunded.

**Update banner, R9 (mock on :8000).** The lead stopped the real backend and ran the mock, changing `latest` between steps; the dismiss state is kept in localStorage `videolens-update-dismissed`.
PASS:
- **UPD-01 (behaviour).** With version_code 99999 the banner shows on cold launch: "Update available. Version 9.9.9 is ready to install." plus "Get the update" and an X.
- **UPD-03.** "Get the update" opens Chrome (`FirstRunActivity`) outside the app, and Back returns to the app unchanged.
- **UPD-06.** No banner for version_code 1 (same as installed), for `latest: null`, or for a 503 on `/api/releases`. The dismiss key was cleared first, and the fetch itself was confirmed through `performance` entries.
- **Dismiss.** The 44×44 X hides the banner and writes `videolens-update-dismissed=99999`. It stays hidden after a cold launch and after a resume. Moving to version_code 100000 brings it back.
- **UPD-07** (checked in the DOM; TalkBack was not run). The banner is `<aside aria-label="App update">`, the X has `aria-label="Dismiss the update notice"`, the icons are `aria-hidden`, and the banner comes first in focus order.

SUPERSEDED (the top banner becomes a centred popup in R10, owner decision): UPD-01 layout and position, UPD-02, UPD-04 and UPD-05. What was seen before the decision:
- Height: 80 px in portrait and a single 45 px row in landscape, in both themes. No overlap with the header and no horizontal scroll.
- Present on History, More (under the scrim), Terms, Privacy and 404.
- **Overlap defect, passed to the R10 popup.** At 320 css px with font ≥1.15, and at 343 px with font 1.3, the "Get the update" pill covers the "Update available." title. 360 px is fine.
- At font 1.3 on the 412 px width, the banner is 153 px tall.

Not re-checked: Welcome and Splash, since showing Welcome again needs `pm clear`.
NOTES:
- a11y: after a dismiss, focus falls back to `<body>`.
- Question: with every path returning 503, the intake shows no server notice at all — no free-runs banner and no "Can't reach the server". LCH-06b only covers an unreachable server.

### 2026-11-02 · android-66 (device QA) · run 12 (refinement 10, `refine10-debug.apk` at ad39660, real backend then mock)

Build installed at 15:39:43. Emulator API 35. Evidence is in `%TEMP%\qa13\`. Part A ran against the real backend; Part B ran against the lead's mock on :8000.

**Part A (real backend).**
- **A1 PASS.** The Terms/Privacy Back link (69×44, y 89–133) sits above the h1 (y 133). Back lands on `/app.html` from all three paths: intake → Terms, More → Privacy, and a cold-opened Terms (via `location.replace`).
- **A2 PASS, with a MINOR.** At 320 css px, at fonts 1.0 and 1.3, intake, History and the result all have scrollWidth 320. The nav theme toggle (44×44, x 260–304) is not clipped.
  - MINOR: on the result, the "Download .md" pill overflows the card. At font 1.3 it runs 7 px past the card border (pill 141–311, card 16–304). At 1.15 it reaches 11 px into the card padding. It fits at 1.0. The row doesn't wrap.
  - Note: changing the font scale recreates the activity, so the open result is lost and the app lands back on the intake.
  - COSMETIC: the History search placeholder is truncated at 320 px.

**Part B, item 3: update popup (MOCK version_code 99999, dismiss key cleared).** PASS.
- **Layout.** Every configuration has the dialog `open` and `:modal`, the card centred (offset 0,0), focus starting on "Get the update", and no overlap or clipping.
  - Portrait 412×863, light and dark: card 16–396 × 312–551, buttons 160×44 side by side. Backdrop `rgba(0,0,0,.45)` in light, `.6` in dark.
  - 320 px and 343 px at font 1.3: buttons stack (240 and 263 wide).
  - Landscape 915×360, light and dark: compact card (no icon), 266–650 × 102–258.
  - Landscape at font 1.3: card 80–280, fits in the height.
  - Caveat: the emulator would not rotate the app (the display reported rotation 1 but the app stayed portrait). Landscape was emulated with `wm size 2400x1080`, a real 915×360 viewport but not a true device rotation.
  - COSMETIC: in landscape at font 1.3, "Get the update" wraps to two lines (both buttons 72 px tall) rather than stacking.
- **Ordering.** A screen recording shows native splash → in-app Splash → intake → backdrop → popup, so the popup appears only after the Splash. Welcome wasn't re-checked, because it shows only once.
- **Dismiss.** A backdrop tap, Escape (keyevent 111), hardware Back and "Later" each close the popup, store `videolens-update-dismissed=99999` and move focus to the H1 `.intake-title` (never `<body>`). Back does not exit the app. Each one persists across a cold launch: no popup.
- **"Get the update"** opens Chrome (`target=_blank`, the mock's href) and closes the popup without storing a dismiss (`null`). Focus goes to the H1, and the popup shows again on the next cold launch.
- **Tab** cycles Later ↔ Get the update inside the dialog.
- Under the mock, every other path returns 503, so the intake behind the popup shows "Can't reach the server right now. You can still open past runs in History."

**Part B, item 4: version comparison.** PASS. Before MOCK 1 and null, the dismiss key was cleared, so a missing popup can only come from the version check.
- **MOCK 100000.** With `99999` stored, the popup comes back on a cold launch. Back then stores `100000`. The text reads "Version 9.9.9" because the mock returns that `version_name` for every code; UpdatePrompt renders the server's `version_name`.
- **MOCK 1** (same as installed) and **`latest: null`.** `/api/releases` returns 200 and no popup shows.

**Part B, item 5: 503.** PASS.
- **MOCK 503 on every path.** `/api/releases` returns 503. No popup shows, and the intake shows "Can't reach the server right now. You can still open past runs in History." with a History link. This answers run 11's question about a silent 503.
- **Recovery.** I backgrounded the app with Home. The lead restored the real backend (3 free runs). When I brought the app back, it re-fetched `/api/free-runs` (200) and `/api/capabilities` (200). The notice gave way to "Limited: link downloads." and "3 free runs left. Add your own key for more."
- The releases check runs on a cold launch only, not on resume.

No real runs were spent. The device was restored afterwards: font 1.0, wm size reset, auto-rotate on, light theme.

### 2026-11-02 · android-66 (device QA) · run 13 (refinement 11, `refine11-debug.apk` at e1f4426, real backend then mock)

Build: a full `adb install --no-streaming -r` (native change: MainActivity `configChanges` gains `fontScale`), lastUpdateTime 16:33:14. Emulator API 35. Evidence is in `%TEMP%\qa14\`, plus `%TEMP%\qa13\R4-*` for the popup shots. The width was set to 320 css px with `wm size 840x2400`. The result was "Me at the zoo - The First YouTube Video", reopened from History.

**Item 1, results header at 320 px: PASS** (one expectation mismatch, one cosmetic).
- **Font 1.0.** The actions stay on one row (copy 44, share 44, "Download .md" 142 at x141–283, all inside the card at 16–304).
- **Fonts 1.15 and 1.3.** "Download .md" moves to its own full-width row (x37–283, 246 wide) inside the card. docSW is 320 at every size.
- **Chevrons.** A real tap on the end chevron pages the row to the end (scrollLeft 0 → 40/41 at 1.0, 0 → 96/97 at 1.3), which shows the start chevron and hides the end one. The start chevron pages back.
- **Chosen tab clears the fades** at 1.0 and 1.3 (underFade=false, inside the list). This includes On-screen chosen while half-hidden under the end fade, and TL;DR chosen from under the start fade, each scrolled clear by `scrollIntoView`. At 1.3, Transcript in the middle stops exactly at the end fade's edge (239).
- **MISMATCH with the brief.** At 320 px and font 1.0 the tabs overflow by 41 px (On-screen runs to 324, the list ends at 287), so the end chevron does show. That is correct behaviour for an overflowing row. The results-view doc's "nothing shows at the normal text size" was verified at 390/1280, not 320.
- **COSMETIC.** The fades sit at 37–81 and 239–283, but `.tab-list` spans 33–287. About 4 px of tab text (a ")" and an "e") peeks out past each chevron; it shows in the 1.0 light and dark shots.

**Item 2, live system font change: PASS.**
- With the result open, the font went 1.0 → 1.15 → 1.3 → 1.0. The pid (15296) and an in-page marker (`window.__qamark`) both survived, so nothing reloaded.
- The URL, the result and the selected tab were kept, and text resized live: body 16 → 18.4 → 20.8 → 16 px, h1 28 → 32.2 → 36.4 → 28 px.
- **Theme toggle** both ways: no reload, the result is kept, and the system bars follow the theme.
- **Rotation** (`wm user-rotation lock 1`, live, to 915×360 and back) and a `wm size` change: no reload, the result is kept.

**Item 3, History at 320 px: PASS.**
- The placeholder reads "Search runs" and fits at fonts 1.0, 1.15 and 1.3: 85, 98 and 111 px of text against 133, 125 and 118 px available.
- The sort select stays on the search row, because there's still room. At font 2.0 it drops below the full-width search field.
- **MINOR, beyond the brief.** At font 1.5 (a standard Android 14 size step) the placeholder truncates to "Search ru" (128 px of text, 108 px available), and the sort has not wrapped yet.

**Item 4, popup in landscape at font 1.3 (MOCK 99999, dismiss key cleared): PASS.**
- Real landscape (915×360) in light and dark: "Get the update" and "Later" each sit on one line (`white-space: nowrap`, scrollWidth equal to clientWidth). The buttons are 162×48 side by side; R10 had a two-line label at 72 px.
- Card 266–650 × 92–268, centred, with no overlap or clipping. The popup stays open across a live rotation.
- 320 px portrait at font 1.3: the buttons stack (240 wide), each label on one line.
- Emulator quirk: a cold launch with the rotation locked to 1 still comes up portrait (the same symptom as run 12). A live rotation of the running app works, so the dark case was measured after a live rotation.

NOTES:
- Not a defect: the source card for "Me at the zoo" reads "Microplastics are accumulating in human brains…". That is the run's stored `source_metadata.description` as yt-dlp fetched it for jNQXAC9IVRw (the uploader's current description), not a mix-up between runs.
- No real runs spent. Partial-outage handling (D-R10-1) was covered on the web, per the lead. The device was restored afterwards: font 1.0, wm size reset, auto-rotate on, light theme, dismiss key null.

### 2026-11-02 · android-66 (device QA) · run 14 (refinement 12, `refine12-debug.apk` at 5ac8522, real backend)

Build: a full `adb install --no-streaming -r`, lastUpdateTime 17:24:48. Emulator API 35. Evidence is in `%TEMP%\qa15\`. The width was set to 320 css px with `wm size 840x2400`. The result was "Me at the zoo - The First YouTube Video", reopened from History. Font changes were made live; the app no longer reloads on them since R11.

**Item 1, tab-row fades at 320 px.**
- **Method.** `fades.js` checks two things at scroll 0, after a real tap on the end chevron, after a real tap on the start chevron, and at mid-scroll:
  - that each visible fade reaches the `.tab-list` edge;
  - that no tab label glyph (Range client rects) lies in an uncovered strip between a fade and the list edge.
  `tabclear.js` checks each chosen tab against the visible fades.
- **Fonts 1.0, 1.3 and 1.5: PASS.**
  - The fades now sit at 33–81 and 239–287, the list's own edges (R11: 37–81 and 239–283). uncoveredStrips=0 and peek=none in every state.
  - A zoomed screenshot at 1.0 mid-scroll shows no glyph past either chevron.
  - The chevrons page the row both ways (scroll 0 → 40/41, 96/97 and 139/140).
  - Every chosen tab is clear of the fades: On-screen, TL;DR, Transcript and Notes, at each of 1.0, 1.3 and 1.5. At 1.3 and 1.5, Transcript stops exactly at the end fade (239), and Notes at 1.5 starts exactly at the start fade (81).

- **Font 2.0: PASS, better than documented.**
  - No peek in any state, and the chevrons page the row (0 → 178 → 0 of 249).
  - Every chosen tab lands clear: On-screen 143–283 at the end, TL;DR 37–115, Notes 81–159, and Transcript 101–239 between both fades.
  - The doc's "geometric limit" (Transcript and On-screen can't clear at 320/2.0) does not occur on the device. Here the list is 254 px wide (33–287), not the ~182 px estimated, which leaves a 158 px band between the fades.
- **No chevrons at the normal text size from 360 px up: PASS.**
  - At 360, 390 and 412 px with font 1.0, both fades are off.
  - At 360 the list is 1 px over (0/1), which is its own end padding, as documented.

**Item 2, History search at 320 and 360 px, fonts 1.0, 1.15, 1.3, 1.5 and 2.0: PASS.**
- `hist.js` compares the placeholder's text width (canvas `measureText` in the input font) against the space inside the input's padding.
- "Search runs" fits in all ten combinations. The sort drops under a full-width field before the placeholder could clip:
  - at 320, from font 1.3 (space available 254 for 111/128/170 px of text at 1.3/1.5/2.0);
  - at 360, from font 1.5.
- Below those thresholds the sort stays on the same row. Closest margin: 360 at 1.3, 111 of 158.
- The R11 failure ("Search ru" at 320/1.5) is gone.

**Item 3, nav menu button at 320/1.5: NOT REPRODUCED on the device** (there is no such button in the installed app).
- The app header holds only the wordmark and the theme toggle, on the result view and on Terms. The toggle is 44×44 at x 260–304, in view, and not clipped by any overflow ancestor.
- Navigation lives in the dock: Analyze 22–111, History 115–205 and More 209–298, labels unclipped (scrollWidth equals clientWidth).
- The menu button the agent saw is presumably the web (non-installed) shell's, which this device can't check.
- COSMETIC, found on the way, in the More sheet at 320/1.5: the theme control's "System" label (text 77–150) is 2 px wider than its segment (77–148) and has no side padding. "Light" and "Dark" have about 11 px each. It fits at 320 for 1.3 and below, and at 360/1.5.

**Item 4, smoke test at 412 px, font 1.0, cold launch, real backend: PASS.**
- **Intake.** No popup. `/api/releases`, `/api/free-runs` and `/api/capabilities` all return 200, and the intake shows "Limited: link downloads." and "3 free runs left."
- **History.** 20 rows, no horizontal scroll.
- **Result** (Test Pattern Video). The actions sit on one row with Download inside the card, and there are no chevrons. Each tab shows its own panel: TL;DR with its key takeaway, Notes with the markdown, Transcript with "No spoken content was detected.", and On-screen with timed text.

No real runs spent. The device was restored afterwards: font 1.0, wm size reset, auto-rotate on, light theme, CDP forward removed, adb reverse 8000 kept.

### 2026-11-02 · android-66 (device QA) · run 15 (refinement 13, `refine13-debug.apk` at a69c188, real backend)

Build: `adb install -r`, lastUpdateTime 18:03:06. Emulator API 35. Evidence is in `%TEMP%\qa16\`.
- **Widths.** 320 css px (`wm size 840x2400`) and 360 css px (`945x2400`).
- **Fonts.** 1.0, 1.3, 1.5 and 2.0, changed live.
- **Measurements.** `m13.js` measures:
  - the header bar, the wordmark's computed font-size and text extent (Range rect), and the toggle;
  - the content band (`main.view-scroll`) and the dock;
  - in the More sheet, each theme segment's rect against its label's glyph extent, plus which layout is in use.
- **Bundle check.** The R13 CSS is in the bundle: `.brand { font-size: min(1.1875rem, 22px) }`, `.nav { min-height: min(4.25rem, 68px) }`, and `@container theme-choice not (min-width: 16em)` / `not (min-width: 12.75em)`.

**Root cause behind items 1 and 2: the WebView's text zoom multiplies px values, and a `min(rem, px)` cap can't hold against it.** At font 2.0, probe elements compute as follows:
- `22px` → 44px;
- `1.1875rem` → 38px;
- `min(1.1875rem, 22px)` → 38px;
- `16px` and `medium` → 32px.

Android's font scale reaches the page through `setTextZoom` (R11). Blink applies that zoom after `min()` has compared the *unzoomed* values (19 vs 22). Rem resolves against an unzoomed 16px root, so the 22px cap never binds: the wordmark is 19 × zoom at every scale. The em container queries likewise never fire. The fieldset is 288 px at 320 and 328 px at 360, against 16em = 256 px and 12.75em = 204 px, whatever the zoom. A desktop browser's text-size setting changes the root/initial font size instead, which is presumably why the web pass saw both mechanisms work. **Question for the lead:** is a CSS-side fix acceptable, for example a cap that is itself expressed as a zoom-independent length? Or should the app pass the scale differently, as the root font size rather than text zoom?

**Item 1, app header (wordmark + theme toggle): FAIL on the 22px cap. It fits and nothing is clipped.**

| css px / font | bar | wordmark font-size | wordmark text | toggle | gap to toggle |
|---|---|---|---|---|---|
| 320 / 1.0 | 68 | 19px | 16–129 | 260–304, 44×44 | 131 |
| 320 / 1.3 | 68 | 24.7px | 16–153 | 44×44 | 107 |
| 320 / 1.5 | 68 | 28.5px | 16–170 | 44×44 | 90 |
| 320 / 2.0 | 68 | **38px** | 16–211 | 44×44 | 49 |
| 360 / 1.0–2.0 | 68 | 19 → 38px | 16–129 … 16–211 | 300–344, 44×44 | 171 … 89 |

- No overflow ancestor clips anything. The wordmark never meets the toggle, and the document is never wider than the viewport.
- The bar stays 68 px at every scale: the 38px wordmark's line box still fits under the 68px min-height.
- **Landscape** (live `wm user-rotation lock 1`, 915×360 css): at font 1.0 the bar is 56 px with a 21px wordmark and the toggle at 834–878, 44×44. At font 2.0 the bar grows to **63 px** because the 42px wordmark exceeds the 56px min-height, and the content band shrinks from 235 to 228 px. I have no R12 landscape bar figure to compare against, so "landscape unchanged" is not verified either way.

**Item 2, More-sheet theme control: FAIL. It does not re-lay out on the device, and labels overflow from 320/1.3.**
- The layout is an indented single row (segments start at 74, head at 20) in every one of the 8 combinations. Neither the full-width row nor the stacked rows ever appear.
- Segments are 71 px wide at 320 and 84 px at 360. Every target is at least 44 px tall (44, or 45 at 2.0): PASS.

| css px / font | System (text vs segment) | Light | Dark |
|---|---|---|---|
| 320 / 1.0 | 88–137 in 77–148, pad 11/11 | pad 19/19 | pad 19/19 |
| 320 / 1.3 | 83–147 in 77–148, pad 6/**1** | pad 14/14 | pad 14/14 |
| 320 / 1.5 | 83–156 in 77–148, **8 px over** | pad 11/11 | pad 11/11 |
| 320 / 2.0 | 83–181 in 77–148, **33 px over** | 158–223 in 152–222, pad 6/0 | 232–298 in 226–297, **1 px over** |
| 360 / 1.0 | pad 18/18 | pad 26/26 | pad 26/26 |
| 360 / 1.3 | pad 10/10 | pad 21/21 | pad 21/21 |
| 360 / 1.5 | 83–156 in 77–161, pad 6/5 | pad 18/18 | pad 17/17 |
| 360 / 2.0 | 83–181 in 77–161, **20 px over** | pad 9/9 | pad 9/9 |

- **Visible effect** (`320-f15-sheet-crop.png`, `320-f20-sheet-crop.png`): "System" runs under the selected Light pill and reads "Syste" at 320/1.5 and 2.0. At 2.0, "Light" fills its pill edge to edge. At 320/1.5 this is **worse than R12** (2 px over then, 8 px now): the new 6px label padding moved the text right without the re-layout that was meant to make room.
- Severity MINOR. The label is still identifiable and tappable, but it is truncated at large text on the narrowest phones.
- **Dark still selects dark: PASS.** A real tap on Dark gives `data-theme=dark`, `dark` checked and stored, and body `rgb(14, 16, 15)`. Tapping Light restores light.

**Item 3, footer and content band: N/A for the footer on Android. The band was measured.**
- The installed app never shows the footer. `.page-end` (the footer's parent) is `display: none` under `data-shell="app"`, on `/app` and on `/terms`, at every width and scale, so its height is 0. The dock replaces it. The 146 → 100px footer change can only be checked in the web shell.
- **Content band** (`main.view-scroll`): 69–775, 706 px tall, with the dock at 783–847 (64 px). That holds at 320 and 360 for fonts 1.0, 1.3, 1.5 and 2.0, and at 412.
- Dock items keep their widths (320: Analyze 22–111, History 115–205, More 209–298; 360: 22–125, 129–231, 235–338), 52 px tall, with no label overflow.

**Item 4, smoke test at 412 px, font 1.0, real backend: PASS.**
- **Intake.** The link field, file input and "Analyze link" are present. "Limited: link downloads." and "3 free runs left." show.
- **History** (dock tap). Platform filters and rows are present.
- **Result** ("Me at the zoo", reopened from History). Tabs are TL;DR, Notes, Transcript and On-screen. Download is at 141–375, 44 px tall, its label inside the pill. Transcript shows its own panel.
- **More sheet.** An indented row with 26–34 px label padding, the same as R12, plus API key, Releases and Privacy rows 56 px tall.
- **Terms.** H1 "Terms", band 706 px. Back returns to `/app`, and Back closes the sheet.
- The document is never wider than 412.

No real runs spent. The device was restored afterwards: font 1.0, wm size reset, auto-rotate on, light theme, CDP forward removed, adb reverse 8000 kept.

### 2026-11-02 · android-66 (device QA) · run 16 (refinement 14, `refine14-debug.apk` at 7318f53, real backend)

**Setup**
- **Build.** `adb install -r`, lastUpdateTime 18:44:11.
- **Reinstall.** I reinstalled at 19:05:36 after a short R13 control for item 7. That reinstall was confirmed: the probe gives scale=1 and `22px` stays 22px.
- **Device.** Emulator API 35, WebView Chrome 124.0.6367.219.
- **Evidence.** In `%TEMP%\qa17\`.
- **Widths.** 320, 360 and 390 css px (`wm size 840x2400` / `945x2400` / `1024x2400`) and 412.
- **Fonts.** 1.0, 1.15, 1.3, 1.5 and 2.0, changed live.
- **Measurements.** `probe14.js` reads:
  - `window.__videolensFontScale`;
  - the `<html>` inline style;
  - the root and body font sizes;
  - a `22px` probe and a `1rem` probe;
  - the wordmark's font size.

  `m13.js` covers the header, band, dock and the More-sheet theme control (as in run 15). `rows14.js` measures the More-sheet row labels against their chevrons, and `cards14.js` measures the intake cards and any word split across lines.

**1. Probe: PASS.**
- Root and body are 16 / 18.4 / 20.8 / 24 / 32px at 1.0 / 1.15 / 1.3 / 1.5 / 2.0, with `<html style="font-size: 115% | 130% | 150% | 200%">`. Scale 1 sets no inline size.
- `22px` computes to 22px at every scale, so text zoom is pinned to 100.

**2. Header: PASS.**

| css px | wordmark at 1.0 / 1.15 / 1.3 / 1.5 / 2.0 | bar | toggle |
|---|---|---|---|
| 320 | 19 / 21.85 / 22 / 22 / 22px | 68 | 44×44 |
| 360 | 19 / 21.85 / 22 / 22 / 22px | 68 | 44×44 |
| 390 | 19 / 21.85 / 22 / 22 / 22px | 68 | 44×44 |

- Nothing is clipped, there is no overlap, and the document is never wider than the viewport.
- The smallest gap to the toggle is 83px, at 320/2.0.
- The brand mark goes from 26 to 30px from 1.15 up.
- **Landscape** (live rotation, 915×360): the bar is 56px at all five scales (R13 grew to 63 at 2.0), the wordmark 21 → 24px (the ≥48rem cap), the toggle 44×44.

**3. Theme control layout: PASS, every cell as expected.**

| css px | 1.0 | 1.15 | 1.3 | 1.5 | 2.0 |
|---|---|---|---|---|---|
| 320 | indented | full | full | stacked | stacked |
| 360 | indented | indented | full | stacked | stacked |
| 390 | indented | indented | indented | full | stacked |

- Every label sits inside its segment, with at least 10px side padding (System at 320/1.3 and 390/1.3 is the tightest).
- Targets are at least 44px: 44 / 51 / 57 / 66 / 88px tall.
- **Dark:** a real tap on Dark in the stacked layout at 320/2.0 gives `data-theme=dark`, `dark` checked and stored, and body `rgb(14, 16, 15)`. Light restores light.

**4. Live font change with a result open: PASS.**
- With "Me at the zoo" open on Transcript, I changed the font 1.0 → 2.0 → 1.0.
- The pid stays 18652 and the `__qamark` marker survives, so there was no reload. The result and tab are kept, and MainActivity stays top-resumed.
- Root goes 16 → 32 → 16px and the H1 28 → 56 → 28px.

**5. Cold launch at 1.5 and 2.0: PASS, with no text-size jump.**
- **Method.** `screenrecord` from before the launch, sampled at 5 fps and tiled (`cold-f15-tile.png`, `cold-f20b-tile.png`).
- **Sequence.** Native splash, then the web Splash ("videolens / Notes from short video"), then the intake.
- **Result.** The first intake frame is already at the scaled size, and later frames don't change size. screenrecord only writes frames on change, and at 2.0 the first intake frame is the last frame. At 1.5 the only later change is the capability notice and the free-runs card arriving and pushing content down; that is data loading, not a size change.
- **Late attach.** CDP attached late (page time about 6.6s), so it reports only the settled values: scale 2, root inline `200%`, root 32px, wordmark 22px. First paint was 1.79s (2.0) and 1.29s (1.5).

**6. /privacy and /terms: PASS.**
- At 2.0, both a document navigation and a `location.reload()` give `__videolensFontScale=2`, root `font-size: 200%`, root 32px and wordmark 22px.
- Changing the font to 1.3 while on /terms applies live (root 20.8px) and survives a reload, so the swapped document-start script holds the new value.
- A true cold launch straight into /terms isn't possible (no deep link), so this used a navigation plus a reload.

**7. Pinch zoom: NOT VERIFIED, and there's evidence it is off at every scale.**
- I couldn't do a real two-finger pinch: `sendevent` on `/dev/input/event2` is permission denied (no root), and `adb input` has no multi-touch.
- CDP `Input.synthesizePinchGesture` leaves `visualViewport.scale` at 1.00 on R14 at 1.3. It does the same on a **control install of R13** at 1.3, where text zoom was 130, so the method doesn't detect zoom either way.
- **Static evidence:** Capacitor 8 `Bridge.java:612` calls `setBuiltInZoomControls(config.isZoomableWebView())`. `CapConfig.java:287` defaults `zoomEnabled` to false, and the app's capacitor config doesn't set it.
- **Doc conflict.** `docs/frontend/android-update-check.md` says "the app's viewport never disables zoom, so nothing is lost". The viewport is `width=device-width, initial-scale=1, viewport-fit=cover`, and touch-action is `auto` throughout, but the WebView-level switch is off.
- **Question for the lead:** was pinch ever available on Android (through Chromium's force-zoom at text zoom ≥130), and is it wanted? A manual check with Ctrl+drag in the emulator window, or on a phone, would settle it.

**8. Smoke test at 412/1.0: PASS.**
- **Intake:** link, file input, the capability notice, and "3 free runs left. Add your own key for more."
- **History:** 19 rows.
- **Result:** tabs TL;DR, Notes, Transcript and On-screen, each with its own panel (765 / 284 / 31 characters). Download is 141–375, 44px tall.
- **More sheet:** pixel-identical numbers to R13 at 412 (indented row, pad 26–34).
- **Terms:** H1 "Terms", band 706. Back returns to /app.
- The document is never wider than 412.

**9. Fallback not in use: PASS.**
- Chrome 124 is well past the ~87 needed for `DOCUMENT_START_SCRIPT`.
- `__videolensFontScale` is set on every document. Text zoom is 100, while the fallback would make `22px` compute to 2× it.
- Logcat shows `Registering plugin instance: FontScale` on each launch.

**New defects found on the way**
- **MINOR: intake cards break words at large text.** The noShrink controls now scale with the root:
  - "Details" (`.cap-toggle`, 167px at 2.0, min-width 2.75rem);
  - "Add key" (`.free-runs .btn`, 182px).

  So the text beside them is squeezed:

  | css px / font | `.cap-summary-text` width | broken words |
  |---|---|---|
  | 412 / 2.0 | 84px | "Limite/d", "downl/oads." |
  | 390 / 2.0 | 63px | "Limited:", "downloads." |
  | 360 / 2.0 | 32px | "Limited:", "link", "downloads." |
  | 320 / 2.0 | — | "Limited:", "link", "downloads." (`intake-320-f20-s.png`) |
  | 320 / 1.5 | 73px | "downloads." |

  - The free-runs text is one word per line at 2.0, with no mid-word breaks.
  - There are no breaks at 1.3 for 320/360/412, at 1.5 for 360/412, or at 1.15 for 320.
  - Screenshot: `intake-412-f20-s.png`.
  - R13 was never measured here, so it's unknown whether this is new.
- **COSMETIC: More-sheet row labels run into their chevrons at 320/2.0.**
  - At 320/2.0, "Releases" (text right edge 283) overlaps its chevron (244–280) by 39px, and "Privacy" by 17px. "Terms" has a 2px gap, and "API key" wraps to two lines.
  - At 360/2.0, Releases has a 1px gap.
  - Every row is fine at 1.5 and below.
  - Screenshot: `320-f20-sheet-s.png`.
- **Observation (question): the dock scales with the root and eats the content band.**
  - Portrait: the dock is 64 / 74 / 83 / 96 / 128px tall and the band 706 / 693 / 680 / 662 / 618px across the five scales.
  - Landscape: the dock is 52 → 104px and the band 235 → **167px** at 2.0, which is 46% of a 360px-tall screen.
  - Is an uncapped dock intended, like the top bar's cap?

No real runs spent. I made one R13 control install for item 7 and then reinstalled R14. The device was restored afterwards: font 1.0, wm size reset, auto-rotate on, light theme, CDP forward removed, adb reverse 8000 kept, and the temporary files on the device deleted.

### 2026-11-02 · android-66 (device QA) · run 17 (refinement 15, `refine15-debug.apk` at 9605e43, real backend)

**Setup**
- **Build.** `adb install -r`, lastUpdateTime 19:48:47.
- **Device.** Emulator API 35, WebView 124.
- **Evidence.** In `%TEMP%\qa18\`.
- **Widths.** 320, 360 and 412 css px.
- **Fonts.** 1.0, 1.3, 1.5 and 2.0, changed live.
- **Scripts.**
  - `cards15.js`: each intake card's text and button rects, row versus stacked, line and word counts, and any word split across lines (Range rects per word).
  - `dock15.js`: the dock's height, the content band, item sizes and label clipping.
  - `align15.js`: the More-sheet row icons and label left edges.
  - Run 16's `probe14.js`, `m13.js` and `rows14.js`.

**1. Intake cards: PASS.**

| css px | 1.0 | 1.3 | 1.5 | 2.0 |
|---|---|---|---|---|
| 320 | row | stacked | stacked | stacked |
| 360 | row | stacked | stacked | stacked |
| 412 | row | row | stacked | stacked |

- No word breaks mid-word in any of the 12 combinations ("Limited:" and "downloads." stay whole).
- "Limited: link downloads." takes at most 2 lines. The free-runs text (10 words) takes at most 4 lines (320/2.0), never one word per line.
- At 320/2.0 the summary text is 178px wide (R14: squeezed to a few px); at 412/2.0 it is 271px (R14: 84px).
- Buttons sit under the text when stacked: "Details" 167×88 and "Add key" 182×88 at 2.0.
- Screenshot: `320-f20-intake-s.png`.

**2. More sheet: PASS.**
- At 320/2.0 the gaps between label and chevron are: Releases **+33px** (R14: 39px overlap), Privacy +55, API key +55, Terms +74. "API key" is back on one line.
- Every gap at every other combination is at least +73px.
- Chevrons are now a fixed 18px.
- **Theme row alignment.** Every row's icon is a fixed 40×40 (R14 scaled it up to about 80px at 2.0), and all five labels share one left edge: 74 at 320/1.0, 80 at 412/1.3, 94 at 320/2.0, the Theme row included.
- Screenshot: `sheet-320-f20-s.png`.

**3. Dock: PASS.**
- **Portrait.** 64px tall (783–847) and the band 706px, at all 12 combinations. R14 grew it to 128px.
- **Items.** 52px tall, 79–120px wide, no label clipped.
- **Landscape** (live rotation, 915×360). The dock is 52px and the band **235px** at 1.0, 1.3, 1.5 and 2.0 (R14: 167px at 2.0). Items are 44px tall, 155 → 275px wide, none clipped.

**4. Regression: PASS.**
- **Probe, header and wordmark:** identical to run 16 at 320 and 360:
  - root 16 / 20.8 / 24 / 32px;
  - `22px` stays 22px;
  - wordmark 19 / 22 / 22 / 22px;
  - bar 68 portrait and 56 landscape;
  - toggle 44×44, nothing clipped.
- **Theme control layouts:**

  | css px | 1.0 | 1.3 | 1.5 | 2.0 |
  |---|---|---|---|---|
  | 320 | indented | full | stacked | stacked |
  | 360 | indented | full | stacked | stacked |
  | 412 | indented | indented | full | stacked |

  - Segment numbers are unchanged from run 16 except the stacked control at 2.0, which is **48px higher** (segments start at 563, not 611): within the allowed shift.
  - At 412/1.3 the indented row starts at 80 (head 26). This width wasn't measured in run 16.
- **Live change 1.0 → 2.0 → 1.0 with "Me at the zoo" open on Transcript.** Same pid (21473), the marker kept, and the tab kept. Root 16 → 32 → 16, H1 28 → 56 → 28, and the dock stays 64.
- **Smoke at 412/1.0.**
  - Intake: link, file, the notice and the free-runs card in one row.
  - History: 19 rows.
  - Result: 4 tabs with their own panels (765 / 31 / 284 characters), Download 141–375, 44px tall.
  - Terms: H1, band 706. Back returns to /app.
  - The document is never wider than the viewport, and light theme is kept.

**Pinch zoom:** still NOT VERIFIED (owner question, see run 16).

No real runs spent. The device was restored afterwards: font 1.0, wm size reset, auto-rotate on, light theme, CDP forward removed, adb reverse 8000 kept.

## Changelog

- 2026-11-02 · android-66 (device QA) · added section 19 (update banner, UPD-01..07) and run 9 (UPD partial on the mock: UPD-01/03 PASS, UPD-04 partial, rest PAUSED) and run 10 (real runs: terms persistence, RUN-01 retry with a YouTube link, RUN-02/02b/03/04/05/07/08, ORI-02, HIS-01, FREE-01..05, RUN-06b/06c/06d/06e, LCH-06b/06c, FREE-02b PASS; FREE-02c not exercised (YouTube 403 mid-download); stale free-runs count after a refund logged as known (R9); stage timings incl. Normalizing ~60 s for a 170 s file); added FREE-02b/02c rows to section 6

- 2026-11-02 · android-66 (device QA) · run 8 Run log: real-run GO stopped by the backend being killed for memory; RUN/FREE/ORI-02/LCH-06c stay BLOCKED, nothing counted against the app
- 2026-11-02 · android-66 (device QA) · added section 18 (refinement 8 cases) and the run 7 Run log (04a9a9c worktree build): NF-01b, NF-02, HOP-01, LOG-01, INT-18, INT-19, STB-01 and NAV/BCK PASS; note on the Terms Back link landing on /app.html
- 2026-11-02 · android-66 (device QA) · THM-01b-6e re-marked BLOCKED (needs physical device) per lead triage; NF-01 and the disabled "Browse files" are being fixed in refinement 8 and will be retested
- 2026-11-02 · android-66 (device QA) · added section 17 (refinement 6 and 7 cases) and the run 6 Run log (afb41d8 worktree build): THM-01b-6a..d, INT-04b, INT-16, INT-17, HIS-08, RTL-01, STB-01 PASS; THM-01b-6e inconclusive on the emulator; NF-01 FAIL (MINOR, unknown paths render the landing page on the bundled app)
- 2026-11-02 · android-66 (device QA) · added section 16 (refinement 5 cases) and the run 5 Run log (324608b): INT-01b landscape, THM-01b-1..5, LCH-06d, LCH-02/03 PASS; THM-01b-6 FAIL (WebView prefers-color-scheme stays dark after an OS flip when the app was launched with a stored Light under OS dark)
- 2026-11-02 · android-66 (device QA) · HIS-03b re-run at 360dp (`wm size 720x1600`, density 320): PASS, no horizontal overflow (scrollWidth 360), Oldest reverses runs and groups; Analyze, History, More sheet and dock fine. LCH-06d recorded PASS-with-note (emulator WebView keeps navigator.onLine true in airplane mode)
- 2026-11-02 · android-66 (device QA) · added the refinement 4 cases (section 15) and the Run log for runs 3 and 4 (2a13890, 03dd55e)
- 2026-11-02 · android-66 (device QA) · added the Run log for the second bundled-APK pass (cc978f7)
- 2026-11-01 · android-66 (device QA) · added the Run log for the first bundled-APK pass
- 2026-11-01 · videolens-ff (lead) · First version of the full Android app test suite, for the bundled-APK QA pass after the Phase 5 refinement fixes.
- 2026-11-02 · frontend agent (refinement 3) · added RUN-06b..e (404 expiry on every path, airplane-mode regression) and ORI-05 (nothing under the dock at rest); LCH-02 is the retest for the dark-launch flash fix
- 2026-11-02 · android-66 (device QA) · run 11: refinement 9 retest on refine9-debug.apk (79d69fc): R9-1..10 PASS except R9-7 partial (the reaches-analysis-then-fails half not exercised); update banner on the mock: dismiss, newer version_code, external link and the no-update states PASS; layout cases SUPERSEDED by the R10 popup; banner overlap at 320/343 css px with large fonts
- 2026-11-02 · android-66 (device QA) · run 12: refinement 10 retest on refine10-debug.apk (ad39660): A1 Back link and A2 320px/font 1.3 PASS (MINOR: "Download .md" pill overflows the result card at font ≥1.15); update popup layout (portrait/landscape-emulated, light/dark, 320/343 at font 1.3), ordering after the Splash, backdrop/Escape/Back/Later dismiss with focus to the H1, "Get the update", Tab trap, MOCK 100000/1/null and 503 with the "Can't reach the server" notice and recovery on resume all PASS; COSMETIC landscape-font-1.3 button label wrap
- 2026-11-02 · android-66 (device QA) · run 13: refinement 11 retest on refine11-debug.apk (e1f4426): results header at 320 (Download own row at 1.15/1.3, chevrons page, chosen tab clear of fades), live font change without reload (also theme and rotation), History "Search runs" at 320 up to font 1.3, and the landscape popup labels on one line at font 1.3 all PASS; mismatch: end chevron shows at 320/font 1.0 (tabs overflow 41px); COSMETIC 4px tab text past each fade; MINOR placeholder truncates at font 1.5
- 2026-11-02 · android-66 (device QA) · run 14: refinement 12 retest on refine12-debug.apk (5ac8522): tab-row fades cover the list edges at 320 for fonts 1.0/1.3/1.5/2.0 with no peek (2.0 also clears every chosen tab, better than the documented limit); no chevrons from 360 at font 1.0; History "Search runs" fits at 320/360 for fonts 1.0–2.0 with the sort wrapping first; smoke PASS; nav menu clip at 320/1.5 not reproduced (no menu button in the app header); COSMETIC: More-sheet "System" segment 2px over at 320/1.5
- 2026-11-02 · android-66 (device QA) · run 15: refinement 13 retest on refine13-debug.apk (a69c188): header fits at 320/360 for fonts 1.0–2.0 with no clip and a 44×44 toggle, but the 22px wordmark cap FAILS (38px at 2.0; WebView text zoom multiplies px after min()); More-sheet theme control FAIL (em container queries never fire, so it stays an indented row and "System" overflows its segment from 320/1.5, 8–33 px); Dark selection PASS; footer N/A on Android (.page-end hidden in the app shell), band 706px steady; smoke at 412 PASS
- 2026-11-02 · android-66 (device QA) · run 16: refinement 14 retest on refine14-debug.apk (7318f53): root font-size follows the system scale (16–32px, 22px probe stays 22), wordmark caps at 22px, bar 68 portrait and 56 landscape at every scale, theme control layouts match all 15 expected cells with padded labels and ≥44 targets, Dark works, live change keeps the result, no cold-launch jump at 1.5/2.0, /privacy and /terms get the scale, fallback unused, smoke PASS; pinch zoom NOT VERIFIED (Capacitor zoomEnabled defaults false); MINOR intake cards break words at 2.0 (and 320/1.5); COSMETIC More-sheet Releases/Privacy labels hit their chevrons at 320/2.0; question on the uncapped dock (landscape band 167px at 2.0)
- 2026-11-02 · android-66 (device QA) · run 17: refinement 15 retest on refine15-debug.apk (9605e43): intake cards stack (320/360 from 1.3, 412 from 1.5) with no mid-word breaks; More-sheet labels clear their chevrons (Releases +33px at 320/2.0) with icons fixed at 40px and labels aligned; dock 64px portrait at every scale, 52px landscape with a 235px band at 2.0; header, wordmark and theme-control numbers unchanged apart from the expected 48px rise of the stacked control; live change and smoke PASS; pinch still NOT VERIFIED
