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

## Changelog

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
