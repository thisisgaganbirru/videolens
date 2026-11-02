# Web app test cases

The full manual/automated test suite for the **web app in a browser tab**
(Chrome / headless Chrome). It is not the installed shell: no Capacitor, no PWA
standalone window, so the installed-only pieces (the splash, the Welcome screen,
the bottom dock) are tested here only as **absent**. The Android suite is
`android-app-test-cases.md`; the two share the case format and, where a feature
exists in both, the IDs' meaning. Report every case as PASS / FAIL / BLOCKED / N/A.

Related docs: `landing-page.md`, `app-shell-layout.md`, `share-intake.md`,
`free-runs.md`, `results-view.md`, `run-history.md`, `run-status-pipeline.md`,
`upload-form.md`, `byok-api-key.md`, `legal-offline-routes.md`, `web-manifest.md`,
`capability-reporting.md`, `design-direction-editorial.md` (all under
`docs/frontend/`), and `docs/error-messaging.md`.

## How it runs

| Item | Value |
|---|---|
| Build under test | **Production build**, never `next dev`: `cd frontend && npm run build`, then `npx next start -p 3016` (a spare port; never touch `:3005` or `:8000`, which belong to the lead and the owner). Record the commit SHA, `versionName` and `npx next --version`. |
| Why production | The service worker, the pre-paint scripts and the redirects only behave like the shipped site in a production build. Dev mode adds an error overlay, HMR websockets and no SW. |
| Browser | **Python** Playwright (the `playwright` module of the system python; Chromium and headless_shell are already in `%LOCALAPPDATA%\ms-playwright`, so no installs). Template harness: the refinement 4 `verify.py` (shell override, `/api` mocks, IndexedDB seeding). Headless for the bulk; one **headed** pass for the focus-ring, contrast and animation cases that need eyes). Record the Chromium version. Also run the Claude-in-Chrome pass for the real-run cases. |
| `/api` | **Mocked** with Playwright route interception (`page.route("**/api/**", …)`) for almost every case: deterministic stages, errors, 404s, slow polls, offline. Fixtures live next to the specs (a `completed` run, a `failed` run, a long-content run, a 404). The real backend is used **only** for the real-run cases (marked **REAL**), and only when the owner has restarted it from their own terminal (`:8000`, without `--reload`; the harness reaps background servers on this machine). |
| Real-run budget | Exactly **one** real link run (RUN-R1) and, if the free-run counter allows, one real file run (RUN-R2). Real runs spend Gemini quota and a device free run. Test link: `https://www.instagram.com/reel/DY2POdZonwq/`. Test file: `ffmpeg -f lavfi -i testsrc=duration=15:size=720x1280:rate=30 -f lavfi -i sine=duration=15 -shortest test-15s.mp4`, plus a 12 s MP3 and an unsupported `.txt`. **Never** enter a real API key; use the dummy `invalid-test-key`. |
| Memory | One build and one browser at a time. Close contexts between spec files. |
| Screenshots | `C:\Users\birru\AppData\Local\Temp\qaweb\<case-id>-<viewport>-<theme>.png` |
| Fresh profile | Each spec starts from a new browser context (empty `localStorage`, IndexedDB, caches, service workers). Cases that need state say so. |

### Viewports and themes

Every **layout** case (marked ▦ in the ID column) runs on all of these; other
cases run once at desktop 1280x800 light unless they say otherwise.

| Name | Size | Notes |
|---|---|---|
| D1280 | 1280x800 | Primary desktop. |
| D1920 | 1920x1080 | Wide: content stays in its column, nothing stretches or floats. |
| D1366 | 1366x768 | Short laptop: the fixed frame must still leave a usable content band. |
| P390 | 390x844 | Phone width in a **browser tab**: top bar with hamburger, no dock. Use a mobile context (`isMobile`, `hasTouch`) for the touch cases. |

Themes: **light** and **dark**. Set dark with the app's own setting (not only
`emulateMedia`), and also run the System-follows cases with
`colorScheme: "dark"`.

### Helpers every spec should use

- `noHScroll(page)`: `document.documentElement.scrollWidth <= innerWidth` and
  the same for `body`. Run after every navigation in a layout case.
- Console collector: record `console.error`, `pageerror` and failed requests
  for the whole spec; the spec fails on any uncaught error not on the allow-list
  in the Run log.
- `frame(page)`: top bar and footer `getBoundingClientRect()` before and after
  scrolling the content band, to assert they did not move.

### Defect report format

`ID · title · severity (BLOCKER / MAJOR / MINOR / COSMETIC) · steps · expected ·
actual · screenshot · viewport · light/dark`. Mark anything you couldn't verify
as a question, not a fact. A defect found in a ▦ case names the viewport.

## 1. Landing page `/`

| ID | Steps | Expected |
|---|---|---|
| LND-01 ▦ | Open `/` cold. | Landing renders: top bar, hero ("Turn any short video into clean notes."), sample result card, How it works, What you get, closing band, footer. No splash and no Welcome (installed-only). |
| LND-02 ▦ | Look at the hero at rest, before any scroll. | The hero **fills the content band** between the fixed top bar and footer: no large dead strip under it and no part of the next section poking in unintentionally. The two CTAs and the sample card are visible without scrolling at D1280/D1366. |
| LND-03 | Click "Start analyzing" (hero) and the closing band's "Start analyzing". | Both go to `/app` (client navigation, no full reload); Back returns to `/`. |
| LND-04 ▦ | Click "See how it works". | URL gains `#how`; the How it works section **scrolls into view centred** in the band (not flush under the top bar, not cut off). Pressing Back removes the hash without leaving the page. |
| LND-05 | Load `/#how` directly. | Same centred position on first paint; no jump after hydration. |
| LND-06 | Sample result card: click each tab (TL;DR, Notes, Transcript, On-screen). | The selected tab and its panel change; `aria-selected` follows; only one panel visible. |
| LND-07 | Sample tabs by keyboard: Tab into the tablist, then ← → Home End. | Roving focus: arrows move and select, Home/End jump to first/last, focus ring visible. Only the selected tab is in the Tab order. |
| LND-08 | The footnote under the sample card. | Present, readable, says it is a sample (not a real result). No broken link. |
| LND-09 | Redirect `/?view=history`, `/?view=api-key`, `/?view=releases`. | Replaced (no extra history entry) with `/app?view=<same>`; the right view renders. Body never flashes the landing first. |
| LND-10 | Redirect the share query: `/?share-target=1&url=https%3A%2F%2Fexample.com%2Fv`, `/?url=…`, `/?text=…`, `/?title=…`. | Replaced with `/app` plus the same query; Analyze shows with the link prefilled (no auto-submit). The query is stripped afterwards and Back does not re-deliver it. |
| LND-11 | `/?utm_source=x`. | **Stays** on the landing (only `view`, `share-target`, `url`, `text`, `title` redirect). |
| LND-12 | After a redirect, press Back. | Leaves the site or goes to the previous page; it never lands on a blank `visibility:hidden` page or loops. |
| LND-13 | Landing copy honesty. | No testimonials, user counts, logos or ratings; "a few free runs" with no number. |
| LND-14 ▦ | Scroll the whole landing. | Only the content band scrolls; top bar and footer stay put (CHR-01 rules). No horizontal scroll. |
| LND-15 | Reduced motion (`reducedMotion: "reduce"`). | No smooth-scroll or animation on `#how`, sample tab change or hero. |

## 2. `/app`, tabs and URL state

| ID | Steps | Expected |
|---|---|---|
| APP-01 | Open `/app`. | Analyze view; the nav shows Analyze active; `document.title` is "VideoLens AI". |
| APP-02 | Click History, API key, Releases in the top bar. | URL becomes `/app?view=history`, `?view=api-key`, `?view=releases`; the view and the active nav item match; no full reload. |
| APP-03 | Click Analyze from another tab. | URL becomes `/app` (no `?view=`). |
| APP-04 | Load each `/app?view=…` URL cold. | The right view renders with the right nav item active. |
| APP-05 | `/app?view=nonsense`. | Falls back to Analyze (or a clear state), no crash, no console error. |
| APP-06 | Switch tabs while a result is open on Analyze. | The result stays under Analyze (state kept) when returning. |
| APP-07 | Browser Back/Forward across Analyze → History → API key → Releases. | Each press restores the previous view and the nav highlight; no tab is skipped or duplicated; the scroll position of the content band is sensible. |
| APP-08 | Reload on each view. | Same view, same URL. |
| APP-09 | Brand logo in the top bar. | A link to `/` (landing) in a browser tab. |
| APP-10 | The nav "Releases" view. | Loads release notes, or a clear offline/error message; never blank. |

## 3. Chrome: top bar, footer, scrolling frame

| ID | Steps | Expected |
|---|---|---|
| CHR-01 ▦ | On `/`, `/app`, History, API key, Releases, `/privacy`, `/terms`, `/offline`: scroll the content band (make it long: a long result, many History rows, legal text). | Top bar and footer **never move**. Only the content band scrolls, and **only when it needs to**: a short page has no scrollbar. |
| CHR-02 ▦ | Compare the top bar and footer on every route above. | **Identical** (same height, links, position, theme toggle). No route has its own variant. |
| CHR-03 ▦ | Content's last line on a long page. | Not hidden behind the footer; some breathing room. |
| CHR-04 ▦ | `noHScroll` on every route above. | Pass at every viewport. |
| CHR-05 | D1366 (768 high): open a long result. | The band is still usable (not squeezed to a sliver); the page scrolls inside the band. |
| CHR-06 | Resize live from D1920 down to P390 on `/app`. | Layout reflows without a reload: nav links collapse to the hamburger below 48rem; no overlap at any width in between (sweep 1920, 1366, 1280, 1024, 800, 768, 600, 480, 390, 360). |
| CHR-07 P390 | Open the hamburger. | A full-screen menu with the four tabs and Privacy/Terms where specified; Escape and a second tap close it; focus returns to the hamburger; the page behind does not scroll. |
| CHR-08 | Footer links Privacy and Terms (desktop). | Open `/privacy` and `/terms` with the same chrome; the crumb/back link returns where you came from. |
| CHR-09 | Scrollbar behaviour. | A scrollbar appears only on the content band, not the whole window; no double scrollbars. |

## 4. Intake: link and file

| ID | Steps | Expected |
|---|---|---|
| INT-01 ▦ | Click "Analyze link" with the field empty. | Error "Paste a link to analyze." **under the field**, the field is focused and `aria-invalid`, the message is tied by `aria-describedby`; no request sent. |
| INT-02 | Type `notaurl`, submit. | Valid-URL error under the field; no request. |
| INT-03 | Untick terms, paste a valid link, submit. | Terms error; the checkbox is marked invalid and focused; Browse files stays enabled (click, Enter or Space shows the same error, opens no picker); no request. |
| INT-04 | Two errors at once (empty link, terms unticked), one press. | Both errors show, each under its own field; focus goes to the link; no request; each message clears only when its own control is edited. |
| INT-05 | Error clears on input. | Typing a valid URL clears the link error immediately (not on next submit). |
| INT-06 | Terms persistence: tick, reload. | Still ticked (`videolens-media-terms-v1`). |
| INT-07 | Terms links. | Terms and Privacy open the legal pages; Back returns to the intake with the typed link kept or cleanly empty (record which). |
| INT-08 | Paste a link with tracking params (`?utm_source=…&igsh=…`). | Accepted unchanged; the displayed link in the run card matches. |
| INT-09 | Whitespace-padded link and a link with a trailing newline. | Trimmed and accepted. |
| INT-10 | Unsupported schemes: `javascript:alert(1)`, `ftp://x`, `file:///x`. | Rejected with the valid-URL error; nothing executes. |
| INT-11 | Very long URL (2,000+ chars). | No layout break; accepted or rejected with a clear message. |
| INT-12 | File picker: Browse files, choose MP4. | "Checking…" then the run starts; duration is read client side. |
| INT-13 | File picker: MOV and MP3. | Accepted. |
| INT-14 | File picker: the `.txt`. | "Only MP3, MP4, and MOV files are supported." |
| INT-15 | File over the size limit (create a sparse >200 MB file) and one over 3 minutes. | A clear per-reason error before any upload begins. |
| INT-16 | Zero-byte file (and a corrupt MP4). | Zero-byte: "This file is empty. Choose another one." and no request. Corrupt MP4: the server's failed run shows, no crash, no stuck spinner. |
| INT-17 | Drag and drop a valid file onto the drop zone (desktop). | Drop zone highlights on dragover, un-highlights on dragleave, and the file is accepted as in INT-12. |
| INT-18 | Drop a `.txt`, then drop two files at once. | The unsupported type shows INT-14's error; with several files, one is used or a clear message appears (record which); no crash. |
| INT-19 | Drop a file **outside** the drop zone. | The browser does not navigate away to open the file; the page stays. |
| INT-20 | Drop zone copy by pointer type. | Mouse: "Drop an audio or video file". Touch context: "Add an audio or video file". |
| INT-21 | Keyboard only (no pointer): Tab through the page. | Order: top bar links → free-runs pill/Add key → link field → Analyze link → Browse files → terms checkbox → terms links → footer. Every stop shows a visible focus ring. |
| INT-22 | Keyboard only: type a link, tick terms with Space, press Enter in the field. | Submits exactly once. |
| INT-23 | Keyboard only: Browse files with Enter/Space. | Opens the native picker. |
| INT-24 | Double-click/double-Enter on Analyze link. | Exactly one `POST /api/runs`; the banner decrements by 1 at most. |
| INT-25 | Enter a link, switch to History and back. | The typed link is still in the field (or cleanly empty; record which). |
| INT-26 | Paste via Ctrl+V and via the browser's autofill. | Both populate the field and validate. |
| INT-27 P390 | Touch: focus the field in a mobile context. | The field and Analyze stay in view above the on-screen keyboard (emulate by shrinking the visual viewport); errors sit under the field, never off-screen. |

## 5. Free runs and API key

| ID | Steps | Expected |
|---|---|---|
| FRE-01 | Open `/app` with `/api/free-runs` mocked to `{remaining: 3}`. | The pill/banner says "3 free runs left." with an Add key button. Singular: `remaining: 1` → "1 free run left." |
| FRE-02 | Click Add key. | Opens the API key view (`/app?view=api-key`). |
| FRE-03 | After a run (mock the counter dropping). | The banner shows the new count without a reload. |
| FRE-04 | `remaining: 0`. | Used-up state: banner with Add key; Analyze and Browse files disabled (or submit explains why); the link field stays editable. |
| FRE-05 | Used-up state, paste a link and press Analyze. | Nothing is submitted; the CTA/banner says why. |
| FRE-06 | `POST /api/runs` mocked to 402. | The used-up state appears and the intake explains it; no stuck spinner. |
| FRE-07 | `POST /api/runs` mocked to 401 (stale device token). | A single silent retry with a fresh token, then success; no error shown to the user. |
| FRE-08 | `/api/free-runs` fails (500 / network). | The banner is hidden or shows a neutral state; the intake still works; no console error spam. |
| FRE-09 | Reload; clear only the device token (`videolens-device-token`) and reload. | A new token is issued; the counter reflects the new token (record the value). |
| KEY-01 | API key view: the lede. | "Optional. You get a few free runs. Add your own Gemini key to keep going." and the steps for getting a key. |
| KEY-02 | Type the dummy `invalid-test-key`, click Save key. | Saved state shown; the free-runs banner hides or changes per design. **Do not submit a run with it.** |
| KEY-03 | Show/hide (eye) toggle. | Reveals and hides the value; the control has an accessible name and `aria-pressed`. |
| KEY-04 | Reload with a key saved. | The key persists (localStorage); the field shows it masked. |
| KEY-05 | Remove/clear the key. | The banner returns (counter as per mock); the stored value is gone from `localStorage`. |
| KEY-06 | Save an empty or whitespace-only key. | A clear validation message; nothing stored. |
| KEY-07 | Network panel after saving. | The key is **never** sent anywhere until a run is submitted; no request on save. |
| KEY-08 | With a dummy key saved, mock a run submit. | `X-Gemini-Api-Key` header present on `POST /api/runs`, absent when no key. (Mocked only; the dummy key must never hit the real backend.) |
| KEY-09 | *Owner-assisted*: a real key, then a real run. | A BYOK run works when free runs are 0. Skip unless the owner does it. |

## 6. A run: stages, connection, expiry

| ID | Steps | Expected |
|---|---|---|
| RUN-01 ▦ (mock) | Submit a link with the run mocked through `queued → processing: downloading → normalizing → uploading_to_gemini → analyzing → complete`. | The film-strip shows four stages advancing, with done ticks and the active stage; the pasted link is shown; the page scrolls to the top on each state change. |
| RUN-02 (mock) | Same for a file run. | "Checking…", then "Sending…", then the stages. |
| RUN-03 | Mock `failed` with an `error` string. | The failed view shows the plain-language message (see `docs/error-messaging.md`), a way to try again, and no raw stack or JSON. The History row shows failed. |
| RUN-04 | Mock each documented error class (download failed, login-gated link, too long, unsupported, quota, server error). | Each has its own sentence; none says only "Something went wrong". |
| RUN-05 | Switch to History while a run is processing, then back. | The run keeps progressing; History shows it as in progress; coming back shows the live stage. |
| RUN-06 | Reload the page mid-run. Variants: (a) on `/app`: the run resumes and reaches the result; (b) reload on `?view=history`: History stays, no resume; (c) reload with the API unreachable (offline document reload lands on `/offline` by design): Connection lost, then Retry now resumes; (d) reload after the server forgot the run: the expired view. | As listed per variant. |
| RUN-07 | "Stop watching and analyze another file". | Returns to a fresh intake; terms stay ticked; the in-flight run remains in History. |
| RUN-08 | Poll the live run with (a) 5xx, (b) network errors. | (a) "Server trouble" pill and "The server is having trouble right now…", with the retry countdown and Retry now; (b) "Connection lost". The run recovers by itself in both. |
| RUN-09 | Poll fails continuously (abort/`route.abort("failed")`). | "Connection lost" with a countdown and **Retry now**; polling backs off; nothing crashes. |
| RUN-10 | While in Connection lost, restore the mock. | The next retry (or Retry now) resumes the run and clears the notice; the stage list continues. |
| RUN-11 | While in Connection lost, `context.setOffline(true)` then `false`. | Same recovery on the `online` event without waiting for the countdown. |
| RUN-12 | Live poll returns **404**. | Within one poll the **expired** view appears ("This run expired") with "Analyze it again" for a link run (prefills the link) or "Choose the file again" for a file run. **Never** stuck on "Connection lost". The History row shows expired, not Processing. |
| RUN-13 | Reopen from History a row the server has forgotten (404 on `GET /api/runs/{id}`) that is stored as still Processing. | Expired view with its actions; the History row badge reads "Expired" (`data-run-status="expired"`). |
| RUN-14 | Reopen from History a row older than the server TTL that **has** a stored result. | The stored result opens from IndexedDB; no network needed (HIS-09). |
| RUN-15 | Expired view, "Analyze it again". | Intake with the original link prefilled; terms ticked; no auto-submit. |
| RUN-16 | `POST /api/runs` error responses. | 500 (plain or JSON): "The server had a problem starting this run. Try again in a moment."; 503 with a curated message: that message; 429 with an exposed `Retry-After: 300`: "...about 5 minutes"; 429 without it: the backend message; 400: its message kept; 422: a generic line. Form usable after each. (The backend does not send Retry-After yet; mock the header.) |
| RUN-17 | Submit while the network is offline. | A clear offline/cannot-reach error in the card; no stuck spinner (see SRV-01). |
| RUN-18 | Tab hidden for 30 s during a run (`document.visibilityState`), then visible. | Polling resumes on return; the stage is current. |
| RUN-19 | Two tabs open on `/app`; start a run in tab A. | Tab B does not steal or duplicate the run; History in tab B shows it after its next refresh (record whether it live-updates). |
| RUN-20 | Run with `prefers-reduced-motion`. | Stage progress does not animate; the active stage is still clear (not conveyed by motion alone). |
| RUN-R1 **REAL** | Real backend, no key: paste the test link, Analyze. | The four stages advance and a result appears. Record each stage's duration (the earlier run: Normalizing was slowest, about 40–60 s). The free-runs banner drops by 1. History shows a portrait poster with a **server thumbnail**. |
| RUN-R2 **REAL** (only if runs remain) | Real backend: the 15 s MP4 via Browse files. | "Checking…", "Sending…", stages, result with a frame poster in History. |

## 7. Results

| ID | Steps | Expected |
|---|---|---|
| RES-01 ▦ | Open a completed run (mock). | Title, source card, four tabs (TL;DR, Notes, Transcript, On-screen) with content. Switching is instant. |
| RES-02 | Tabs by keyboard. | The tablist has `role=tablist`, tabs `aria-selected`, panels `aria-labelledby`; arrows/Home/End move; focus ring visible. |
| RES-03 | Transcript: search box and the Timestamps toggle. | Search highlights or filters; the toggle shows/hides times; an empty result shows a clear "no matches". |
| RES-04 | Source card for a link run. | Platform badge, Original post link, author, caption with Show more/less, likes/comments, posted date. |
| RES-05 | Original post link. | Opens in a new tab with `rel="noopener noreferrer"`; the app tab stays. |
| RES-06 | Source card for a file run. | File name and duration; no broken link fields or "undefined". |
| RES-07 | Copy on each tab. | The control's label or tooltip says what it copies (**this tab**); the check/confirmation appears; `navigator.clipboard.readText()` (grant the permission) equals that tab's text. |
| RES-08 | Share (or "Share" fallback) in a browser without `navigator.share`. | A graceful fallback (copy the full markdown, or hidden); no unhandled rejection. With `navigator.share` stubbed, it receives the **full markdown document**. |
| RES-09 | Download .md. | A file is downloaded with a sensible name (derived from the title, safe characters only); opening it shows the **full markdown** (title, TL;DR, notes, transcript, on-screen). |
| RES-10 | Markdown rendering in Notes: headings, nested lists, bold/italic, inline and fenced code, links, blockquote, table, horizontal rule. | Each renders correctly and wraps inside the band. |
| RES-11 | Hostile content in the mocked result: `<script>alert(1)</script>`, `<img src=x onerror=…>`, `[x](javascript:alert(1))`, raw HTML. | Rendered as inert text or sanitised; no script runs; the `javascript:` link is not clickable. |
| RES-12 | Long content: a 30k-word transcript, a 2,000-char unbroken string, a very long title, 200 notes bullets. | No horizontal scroll; the band scrolls; the UI stays responsive (< 1 s to switch tabs); the last line is not hidden behind the footer. |
| RES-13 | Empty and null fields: no on-screen text, no transcript, no summary. | A clear empty state per tab; no "null"/"undefined". |
| RES-14 | Non-Latin and RTL content. | No tofu; an Arabic Notes fixture renders `direction: rtl` (bullets on the right) and English stays LTR; layout holds. |
| RES-15 | "Analyze another file" after a result. | Fresh intake with an **empty** link field; terms stay ticked. |
| RES-16 | Result page, print preview (Ctrl+P). | Readable; the fixed chrome does not cover content. (COSMETIC if not.) |

## 8. History

| ID | Steps | Expected |
|---|---|---|
| HIS-01 ▦ | After two mocked runs (one link, one file) open History. | A poster grid grouped by day ("Today"); each card: portrait/frame poster, platform badge, duration, title, "Today, h:mm". |
| HIS-02 | Empty History. | "No runs yet." and an "Analyze a video" button that goes to Analyze. |
| HIS-03 | Search (type part of a title, a platform, a caption word). | The grid filters live; clearing restores it; a no-match state is clear. |
| HIS-04 | Platform filter chips All / Instagram / TikTok / YouTube / Files. | Each filters correctly; the active chip is marked (`aria-pressed`); combining with search works. |
| HIS-05 | Sort Newest / Oldest. | Order flips; groups re-order consistently. Sort is a control reachable by keyboard; on P390 it is present in the filter row (it was hidden in an older build; record the state). |
| HIS-06 | Groups across days (seed IndexedDB with runs dated today, yesterday, last week, last month). | Group headings are correct and ordered. The cap of 20 is applied when a run is written (`historyStore`), so seed more than 20 through the app's write path, not by writing IndexedDB directly. |
| HIS-07 | Open a card. | The full result renders; the URL/nav state is sensible; Back returns to History with scroll and filters preserved (record which). |
| HIS-08 | Open a failed and an expired card. | Each shows its own view (see RUN-03, RUN-12). |
| HIS-09 | **Offline reopen:** with a completed run stored, `context.setOffline(true)`, open History and the card (the page is already loaded). | The full result renders from IndexedDB; nothing waits on the network; no error banner. |
| HIS-10 | **Offline cold load:** after one online visit (SW installed), set offline and load `/app?view=history`. | The page loads from the service-worker cache and History is usable; a quiet offline hint at most. |
| HIS-11 | Delete or clear a row/History (if the control exists). | Confirms first; only that row is removed. **Never "clear all".** If no control exists, N/A. |
| HIS-12 | Storage failure: block IndexedDB (`indexedDB` throwing) before load. | The app still works for a single run; History shows a clear "can't save history here" state or stays empty; no crash. |
| HIS-13 | Reload after runs; open DevTools Application → IndexedDB. | Rows persist; the DB name/schema matches `run-history.md`; `navigator.storage.persist()` was requested once. |
| HIS-14 | One-time import of the server history (`videolens-history-imported`). | Runs only once; a second load does not duplicate rows. |
| HIS-15 | Thumbnail failures: a row with a broken/oversize `thumbnail`, and an audio run. | A neutral placeholder, never a broken-image icon; the card keeps its size. |

## 9. Theme

| ID | Steps | Expected |
|---|---|---|
| THM-01 | The header toggle (sun/moon). | Flips light/dark on every element at once; writes `videolens_theme`; has an accessible name and state (`aria-pressed` or equivalent). |
| THM-02 | Where present (More / a settings row), choose System, Light, Dark. | Each applies immediately. System follows `prefers-color-scheme`. The browser-tab web shell may not expose More; record where the control lives or N/A. |
| THM-03 | Set Dark, reload (10 times via script). | **No flash** of light on any route (`/`, `/app`, History, API key, Releases, `/privacy`, `/terms`, `/offline`): first paint is already dark. Capture a screenshot on `domcontentloaded` and assert background colour. |
| THM-04 | Set Light, reload, with `colorScheme: "dark"` on the OS. | Stays light (explicit setting wins). |
| THM-05 | System theme, flip `emulateMedia({ colorScheme })` live. | Follows without reload. |
| THM-06 ▦ | Visual sweep of every route and state in light and dark: landing, intake with errors, banner, run stages, result tabs, History, API key, Releases, legal, offline, Connection lost, expired, failed. | No invisible text, no light-on-light/dark-on-dark, no leftover hard-coded colours, borders and focus rings visible, images/posters not clipped. |
| THM-07 | Corrupt `videolens_theme` (`"purple"`). | Falls back to System; no console error. |
| THM-08 | `meta[name=theme-color]` and `color-scheme`. | Match the active theme. |

## 10. Releases, legal and offline pages

| ID | Steps | Expected |
|---|---|---|
| REL-01 | `/app?view=releases`. | Release notes list (newest first) with versions and dates; links open correctly; no raw markdown or `undefined`. |
| REL-02 | Releases with `/api/releases` mocked to 500 / empty. | A clear message or empty state; no crash. |
| LEG-01 ▦ | `/privacy` and `/terms`. | Render inside the shared chrome (same top bar and footer), headings and text readable, content in the scrolling band, no horizontal scroll. |
| LEG-02 | The crumb/back link on each. | Returns to the view the user came from (Back rules in `app-shell-layout.md`); a cold load goes to `/`. |
| LEG-03 | Cold-load `/privacy` then Back. | Goes to `/` or the previous page; never a blank screen. |
| LEG-04 | In-page anchors and links in the legal text. | Work; external links open safely. |
| OFF-01 | Install the service worker: visit `/app` online, wait until `navigator.serviceWorker.ready`. | A registration exists for `/`; precache lists the shell routes. |
| OFF-02 | `context.setOffline(true)`, navigate to `/app`. | The app shell loads from cache. |
| OFF-03 | Unknown path, online and offline. | Online: the 404 page with the shared chrome and one `<main>`. Offline: `/offline`. |
| OFF-04 | `/offline` directly (online). | Renders the same page; its links are plain `<a>` (works with no client router); "Try again" retries and returns when online. |
| OFF-05 | Offline, reload `/`, `/privacy`, `/terms`. | Each loads from the cache. |
| OFF-06 | Go back online while on `/offline`. | The page recovers (retry works or the app returns on its own); no stuck state. |
| OFF-07 | Ship an updated build (rebuild with a trivial change, restart `next start`) with a tab open on the old SW. | The new SW takes over without trapping the user on stale assets; a reload gets the new build; no infinite reload. |
| OFF-08 | `/manifest.webmanifest`. | Valid JSON: name, icons, `start_url` (`/app`), `display`, `share_target.action` (`/app`), theme colours. Icons load (200). |
| OFF-09 | API calls are **not** cached by the SW. | Offline `GET /api/free-runs` fails visibly (not served stale from the cache). |

## 11. Server unreachable

| ID | Steps | Expected |
|---|---|---|
| SRV-01 | `/api/**` aborted for the whole load. | Analyze shows a calm inline "can't reach the server" notice; the page is otherwise usable; no crash, no blank screen. |
| SRV-02 | Notice recovery: restore the mock, fire `online`/focus. | The notice clears quietly after one successful check; the banner reappears. |
| SRV-03 | The notice never blocks. | The link field, Browse files and History all still work; submitting while unreachable shows RUN-17's error. |
| SRV-04 | `/api/capabilities` returns degraded (`media_tools` unavailable). | A clear status with the reason from `capability-reporting.md`; no raw JSON. |
| SRV-05 | Wrong `NEXT_PUBLIC_API_BASE_URL` / CORS failure (mock a CORS error). | The same unreachable notice; one console error at most per request, no loop. |
| SRV-06 | Slow server: delay `POST /api/runs` by 10 s. | A busy state on the button; no double submit; the message is calm; Cancel/back works. |

## 12. Accessibility

| ID | Steps | Expected |
|---|---|---|
| A11-01 ▦ | Tab through each route from the top. | Logical order, no traps, no off-screen stops; **every** focusable shows a visible focus ring in both themes (≥ 3:1 against its surroundings). |
| A11-02 | Skip link (if present) / landmarks. | One `<main>`, a `<nav>` with a label, a `<footer>`; headings do not skip levels (one `<h1>` per page). |
| A11-03 | Tabs (landing sample, result tabs): ARIA. | `role=tablist/tab/tabpanel`, `aria-selected`, `aria-controls`, roving `tabindex`. |
| A11-04 | Form errors. | Each error is tied to its field with `aria-describedby`, the field has `aria-invalid="true"`, and the message is announced (`role="alert"` or a live region) exactly once. |
| A11-05 | Run progress. | The stage change is announced politely (`aria-live=polite`) and the film-strip has a text alternative; "Connection lost" is announced. |
| A11-06 | Icon-only buttons (theme toggle, eye, copy, share, hamburger, play on posters). | Each has an accessible name. |
| A11-07 | Contrast spot checks, light and dark: body text, muted text, placeholder, disabled buttons, link text, the green CTA label, chips (selected and not), banner text, error text, focus ring. | Text ≥ 4.5:1, large text and UI parts ≥ 3:1. Record measured ratios for the ones within 10% of the limit; use `docs/frontend/design-direction-editorial.md`'s dark-value table as the reference. |
| A11-08 | Reduced motion (`reduce`). | No parallax/auto-animation; transitions are instant or very short; nothing essential is motion-only. |
| A11-09 | Zoom: 200% and 400% (via `deviceScaleFactor` or CSS zoom) at D1280. | Content reflows; no clipped text; the fixed top bar and footer don't consume the whole screen (record the band height at 400%). |
| A11-10 | Text-only resize: root font-size 200%. | No overlap; buttons keep their labels. |
| A11-11 | Screen-reader names for the More/hamburger dialog. | `aria-modal`, labelled, Escape closes, focus is trapped while open and restored after. |
| A11-12 | `axe-core` on each route (light and dark). | No serious or critical violations; list the minor ones. |
| A11-13 | Target size at 390 wide (inline links inside a sentence are exempt). | `.terms-box` is 44x44; footer links are at least 24 px tall; other controls at least 24 px. |
| A11-14 | Colour is never the only signal (errors, active tab, stage state). | An icon, text or shape accompanies the colour. |

## 13. Stability and the browser

| ID | Steps | Expected |
|---|---|---|
| STB-01 | Console for the whole spec on every route. | 0 uncaught errors, 0 hydration warnings ("Hydration failed", "did not match"), 0 "Encountered a script tag". List any warning with the route. |
| STB-02 | Network for the whole spec. | No 4xx/5xx other than ones deliberately mocked; no requests to third-party hosts (fonts and analytics are served first-party or absent); no `localhost:3005` references in a production build. |
| STB-03 | Browser **Back and Forward** over a long path: `/` → `/app` → History → open result → API key → Releases → `/privacy`, then Back ×6 and Forward ×6. | Each step shows the right page and state; no blank frame, no stuck redirect, no duplicated entries from the landing redirect. |
| STB-04 | Reload at every step of STB-03. | Same page. |
| STB-05 | Open a result, press Back. | History (or the previous view), not a blank page. |
| STB-06 | Stress: 20 rapid tab switches, then 20 rapid theme toggles. | No error, no layout break. |
| STB-07 | Memory/idle: leave a result open for 2 minutes (`page.waitForTimeout`) and a polling run for 5 minutes (mocked slow). | No growth in polling frequency, no console errors, the timer count stays flat (`getEventListeners`/performance sample). |
| STB-08 | Private/blocked storage: run with `localStorage` access throwing. | The app loads and works for a session; features that need storage degrade without a crash (theme falls back to System; terms not remembered). |
| STB-09 | Different browsers' basics (if time): Firefox and WebKit in Playwright for LND, INT, RES, HIS smoke. | Record any divergence; not blocking. |
| STB-10 | `next start` log for the whole session. | No server-side exception stack traces. |
| STB-11 | Lighthouse (desktop and mobile) on `/` and `/app`. | Record Performance, Accessibility, Best Practices, SEO; Accessibility ≥ 95 expected; record anything below. |
| STB-12 | Security headers and cookies. | Record the response headers (CSP if any, `X-Content-Type-Options`, `Referrer-Policy`); no cookies are set by the frontend. |

## Run log

### 2026-11-02 · frontend-43 · run 1 (mocked web suite, HEAD 03dd55e)

Production build (`npm run build`), `next start -p 3016`, headless Chromium (chrome-headless-shell 1217) via Python
Playwright, one browser at a time, `/api` mocked by route interception. Real backend not used: RUN-R1 and RUN-R2 are
**BLOCKED** (backend stopped for memory, awaiting owner restart). Earlier the same day one real link run was done by hand in
Chrome (Instagram reel, no key): Downloading to Analyzing to result, banner 3 to 2, History poster present. Screenshots:
`%TEMP%\qaweb\<case>-<viewport>-<theme>.png`. No source edits, no git writes.

**Totals: 277 PASS · 20 FAIL · 2 BLOCKED · 2 N/A.** No MAJOR defects; 12 MINOR findings below.
Layout cases (no horizontal scroll, identical top bar and footer on every route, fixed frame, short pages without a scrollbar) were
run on D1280, D1920, D1366 and P390 in light and dark: all PASS. Console: only expected noise from the mocks (404/429/500 resource
lines, "Service Worker registration blocked by Playwright") plus a CSS preload-not-used warning on 10 page loads (cosmetic).

**Findings (all MINOR; severity is the tester's):**

| ID | Case | Finding |
|---|---|---|
| D1 | INT-04 | With an empty link and terms unticked, only the link error is shown; the terms error never appears next to it. Expected: both, each under its field. |
| D2 | INT-16 | A zero-byte `.mp4` is accepted and POSTed; nothing client side rejects it. |
| D3 | RUN-06 | Reloading mid-run drops back to a fresh intake. The run stays "Processing" in History (open it from there) but does not resume on its own. |
| D4 | RUN-08 | The first 500 on a poll shows "Connection lost" (docs say any poll error does); three blips take about 30 s to clear. The case text expects isolated blips to be silent. Owner decision: change the case or the behaviour. |
| D5 | RUN-13 | Reopening a forgotten Processing run shows the correct expired view, but the History row then reads "Failed" (stored as failed + EXPIRED_MESSAGE), not expired. |
| D6 | RUN-16 | A 5xx with a non-JSON body shows "Could not create run (500)"; a JSON `detail` is shown verbatim ("boom", "Rate limit"). The form stays usable. 429 text has no "try again in N" (mock sent no Retry-After). |
| D7 | HIS-06 | 25 stored runs all render; the cap of 20 is server-side only. Probably the case is wrong, not the app. |
| D8 | OFF-03 / CHR | An unknown URL shows the bare Next 404 with no header or footer, online and offline (breaks "same chrome on every route"). |
| D9 | A11-02 | No `<main>` landmark on any route (4 `nav`s are present and labelled). |
| D10 | A11-07 | "Open Google AI Studio" link on the API key view: 4.22:1 in light (needs 4.5). |
| D11 | A11-13 | At 390 wide: terms checkbox 20x20, footer Terms/Privacy 18 px tall (under 24 px). |
| D12 | A11-09 | At 320x200 (400 % zoom) the content band is 59 px tall; nothing overflows horizontally. Informational. |

**Not machine-judged:** THM-06 and RES-14 need a visual look at the screenshots; A11 keyboard checks beyond tab order, screen reader
output and HIS-04 `aria-pressed` were not verified (harness). OFF-09 is N/A with a route mock.

**Per-case results:**

| Case | Result | Note |
|---|---|---|
| INT-01 | PASS | {"msg": "Paste a link to analyze.", "invalid": "true", "desc": "url-error", "focused": "media-url", "posts": 0} |
| INT-02 | PASS | 'Enter a valid public HTTP or HTTPS URL.' |
| INT-05 error clears on valid input | PASS | error still shown after valid input |
| INT-10 unsafe schemes rejected | PASS | posts=0 |
| INT-08 tracking params accepted (field) | PASS |  |
| INT-03 | PASS | {"termsErr": 1, "invalid": "true", "focused": true, "posts": 0, "browseDisabled": true} |
| INT-03 browse disabled | PASS | Browse files not disabled with terms unticked |
| INT-04 two errors | FAIL | D1: only the link error shows; the terms error never appears alongside it |
| INT-04 fixing terms clears only terms | FAIL | follows D1 |
| INT-06 terms persistence (unticked then reload) | PASS | ticked state tested below |
| INT-06 terms persist | PASS |  |
| INT-07 terms links | PASS | ['/terms', '/privacy'] |
| INT-12 file input exists | PASS | count=1 accept=.mp3,.mp4,.mov,audio/mpeg,video/mp4,video/quicktime |
| INT-14 .txt rejected | PASS |  |
| INT-14 posts | PASS |  |
| INT-16 zero-byte mp4 | FAIL | D2: a 0-byte .mp4 is accepted and POSTed (the server must reject it) |
| FRE-01 remaining=3 | PASS | '3 free runs left. Add your own key for more.Add key' |
| FRE-02 Add key -> api-key | PASS | ?view=api-key |
| FRE-01 remaining=1 | PASS | '1 free run left. Add your own key for more.Add key' |
| FRE-04 used-up state | PASS | {"pill": "You have used your free runs. Add your own key to keep going.Add key", "submitDisabled": true, "fieldEnabled": true, "browseDisabled": true} |
| FRE-05 nothing submitted at 0 | PASS | posts=0 |
| FRE-06 402 handled | PASS | text='videolens Analyze History API key Releases  3 free runs left. Add your own key for more.  Add key  NEW ANALYSIS  Turn any short video into clean |
| FRE-07 401 retried once silently | PASS | posts=2 |
| FRE-08 free-runs 500 intake still works | PASS | pill=0 |
| KEY-01 lede | PASS |  |
| KEY-06 whitespace key not stored | PASS | [] |
| KEY-02 saved to localStorage | PASS | ['videolens-gemini-api-key'] |
| KEY-03 eye toggle has name | PASS | ['Toggle theme', 'Menu', 'Show key', 'Save key', 'Remove key', 'More'] |
| KEY-02 banner hidden/changed with key | PASS | pill count with key saved = 0 |
| KEY-08 X-Gemini-Api-Key on POST (mock) | PASS | header present=True |
| KEY-08 header absent without key | PASS |  |
| RUN-01 stages then result | PASS | seen=['Downloading', 'Normalizing', 'Uploading', 'Analyzing'] |
| RUN-01 link shown | PASS |  |
| RUN-01 layout noHScroll D1280 | PASS |  |
| RUN-01 layout noHScroll D1920 | PASS |  |
| RUN-01 layout noHScroll D1366 | PASS |  |
| RUN-01 layout noHScroll P390 | PASS |  |
| RUN-03 failed shows message | PASS | poll lands ~5s after submit; 'Analysis failed: This link can't be downloaded...' plus Try again |
| RUN-08 isolated 500s no 'Connection lost' | FAIL | D4: the first 500 on a poll shows Connection lost; recovers on its own (~30s for 3 blips) |
| RUN-09 Connection lost shown | PASS | videolens Analyze History API key Releases Connection lost Connection lost  Check your network. The page reconnects on its own and picks up where it l |
| RUN-10 recovers via Retry now | PASS |  |
| RUN-12 live 404 -> expired (link) | PASS | videolens Analyze History API key Releases Expired This run expired  The server keeps a run for an hour, and this one's result never reached this devi |
| RUN-12 live 404 -> expired (file) | PASS | videolens Analyze History API key Releases Expired This run expired  The server keeps a run for an hour, and this one's result never reached this devi |
| RUN-13 reopen forgotten Processing row | PASS | videolens Analyze History API key Releases Expired This run expired  The server keeps a run for an hour, and this one's result never reached this devi |
| RUN-13 row turns expired | FAIL | D5: expired view is right, but the History row reads 'Failed', not expired |
| RUN-14 stored result opens without network | PASS |  |
| RUN-16 429 message and form usable | PASS | videolens Analyze History API key Releases  3 free runs left. Add your own key for more.  Add key  NEW ANALYSIS  Turn any short video into clean notes |
| RUN-16 500 message and form usable | FAIL | D6: 5xx without JSON shows 'Could not create run (500)'; JSON detail shown verbatim; form usable |
| RUN-17 offline submit clear error, no spinner | PASS | 'Can't reach the server right now. You can still open past runs in History.' (rerun with aborted requests) |
| RUN-06 reload mid-run resumes | FAIL | D3: reload returns to a fresh intake; the run stays 'Processing' in History |
| RUN-R1 REAL | BLOCKED | backend stopped (memory), awaiting owner restart |
| RUN-R2 REAL | BLOCKED | backend stopped (memory), awaiting owner restart |
| RES-01 noHScroll D1280 light | PASS |  |
| RES-01 noHScroll D1280 dark | PASS |  |
| RES-01 noHScroll D1920 light | PASS |  |
| RES-01 noHScroll D1920 dark | PASS |  |
| RES-01 noHScroll D1366 light | PASS |  |
| RES-01 noHScroll D1366 dark | PASS |  |
| RES-01 noHScroll P390 light | PASS |  |
| RES-01 noHScroll P390 dark | PASS |  |
| RES-02 tablist ARIA | PASS | [['TL;DR', 'true', 'result-panel-summary'], ['Notes', 'false', 'result-panel-markdown'], ['Transcript', 'false', 'result-panel-transcript'], ['On-scre |
| RES-07 copy per tab content | PASS | {'TL;DR': ['Copy TL;DR', 'Summary text.'], 'Notes': ['Copy notes', '# Heading One\r\n\r\n## Heading Tw'], 'Transcript': ['Copy transcript', '[00:00] H |
| RES-07 copy label names the tab | PASS | {'TL;DR': 'Copy TL;DR', 'Notes': 'Copy notes', 'Transcript': 'Copy transcript', 'On-screen': 'Copy on-screen text'} |
| RES-08 share control present | PASS | share count=0 (record) |
| RES-09 download .md full document | PASS | name=result-title.md size=501 |
| RES-10 markdown renders | PASS | {"h1": 0, "h2": 2, "strong": 1, "em": 1, "code": 2, "a": 1, "ul": 2, "ol": 1, "bq": 1, "table": 1, "hr": 1, "pre": 1, "xss": false, "jsLink": false, " |
| RES-11 hostile content inert | PASS | {"xss": false, "jsLink": false, "script": 0} |
| RES-03 transcript search control | PASS | controls=[] (record) |
| RES-04 source card | PASS | text sample='videolens Analyze History API key Releases  SOURCE  No source details for this r' |
| RES-05 external links noopener | PASS | rel=noreferrer (implies noopener) |
| RES-15 another -> empty field, terms kept | PASS |  |
| RES-12 long content D1280 | PASS | [('TL;DR', True, 0.14), ('Notes', True, 0.2), ('Transcript', True, 0.31), ('On-screen', True, 0.28)] |
| RES-12 long content P390 | PASS | [('TL;DR', True, 0.16), ('Notes', True, 0.22), ('Transcript', True, 0.25), ('On-screen', True, 0.2)] |
| RES-13 empty fields no null/undefined | PASS | [] |
| RES-14 non-Latin renders, no hscroll | PASS | visually reviewed: Hindi, CJK, emoji render, no tofu. Note: the Arabic summary is left-aligned (no dir=auto), minor |
| LND-01 D1280 light | PASS |  |
| LND-02 D1280 light | PASS | {"heroTop": 77, "heroBottom": 743, "hdBottom": 77, "ftTop": 744, "ctaBottom": 622, "vh": 800} |
| CHR-04/LND-14 noHScroll D1280 light / | PASS |  |
| LND-01 D1280 dark | PASS |  |
| LND-02 D1280 dark | PASS | {"heroTop": 77, "heroBottom": 743, "hdBottom": 77, "ftTop": 744, "ctaBottom": 622, "vh": 800} |
| CHR-04/LND-14 noHScroll D1280 dark / | PASS |  |
| LND-01 D1920 light | PASS |  |
| LND-02 D1920 light | PASS | {"heroTop": 77, "heroBottom": 1023, "hdBottom": 77, "ftTop": 1024, "ctaBottom": 762, "vh": 1080} |
| CHR-04/LND-14 noHScroll D1920 light / | PASS |  |
| LND-01 D1920 dark | PASS |  |
| LND-02 D1920 dark | PASS | {"heroTop": 77, "heroBottom": 1023, "hdBottom": 77, "ftTop": 1024, "ctaBottom": 762, "vh": 1080} |
| CHR-04/LND-14 noHScroll D1920 dark / | PASS |  |
| LND-01 D1366 light | PASS |  |
| LND-02 D1366 light | PASS | {"heroTop": 77, "heroBottom": 711, "hdBottom": 77, "ftTop": 712, "ctaBottom": 606, "vh": 768} |
| CHR-04/LND-14 noHScroll D1366 light / | PASS |  |
| LND-01 D1366 dark | PASS |  |
| LND-02 D1366 dark | PASS | {"heroTop": 77, "heroBottom": 711, "hdBottom": 77, "ftTop": 712, "ctaBottom": 606, "vh": 768} |
| CHR-04/LND-14 noHScroll D1366 dark / | PASS |  |
| LND-01 P390 light | PASS |  |
| LND-02 P390 light | PASS | {"heroTop": 69, "heroBottom": 2310, "hdBottom": 69, "ftTop": 772, "ctaBottom": 416, "vh": 844} |
| CHR-04/LND-14 noHScroll P390 light / | PASS |  |
| LND-01 P390 dark | PASS |  |
| LND-02 P390 dark | PASS | {"heroTop": 69, "heroBottom": 2310, "hdBottom": 69, "ftTop": 772, "ctaBottom": 416, "vh": 844} |
| CHR-04/LND-14 noHScroll P390 dark / | PASS |  |
| LND-03 hero CTA | PASS | /app |
| LND-03 back to / | PASS | / |
| LND-03 closing CTA | PASS |  |
| LND-04 D1280 | PASS | {"hash": "#how", "eTop": 77, "eBottom": 743, "hdBottom": 77, "ftTop": 744, "midDelta": -0.0, "fits": true} |
| LND-04 back removes hash D1280 | PASS | http://localhost:3016/ |
| LND-04 D1920 | PASS | {"hash": "#how", "eTop": 77, "eBottom": 1023, "hdBottom": 77, "ftTop": 1024, "midDelta": -0.0, "fits": true} |
| LND-04 back removes hash D1920 | PASS | http://localhost:3016/ |
| LND-04 D1366 | PASS | {"hash": "#how", "eTop": 77, "eBottom": 711, "hdBottom": 77, "ftTop": 712, "midDelta": -0.0, "fits": true} |
| LND-04 back removes hash D1366 | PASS | http://localhost:3016/ |
| LND-04 P390 | PASS | {"hash": "#how", "eTop": 88, "eBottom": 694, "hdBottom": 69, "ftTop": 772, "midDelta": -29, "fits": true} |
| LND-04 back removes hash P390 | PASS | http://localhost:3016/ |
| LND-05 /#how direct | PASS | [77, 743] |
| LND-06 click tabs | PASS |  |
| LND-07 keys | PASS | [['sample-tab-notes', 1], ['sample-tab-transcript', 2], ['sample-tab-onscreen', 3], ['sample-tab-tldr', 0], ['sample-tab-onscreen', 3]] |
| LND-07 roving tabindex | PASS | [-1, -1, -1, 0] |
| LND-08 footnote | PASS |  |
| LND-13 no fake social proof | PASS |  |
| LND-09 history | PASS | /app?view=history |
| LND-09 api-key | PASS | /app?view=api-key |
| LND-09 releases | PASS | /app?view=releases |
| LND-10 share-target | PASS | path=/app field='https://example.com/v' search= |
| LND-10 share-target prefill | PASS | 'https://example.com/v' |
| LND-10 share-target query stripped | PASS |  |
| LND-10 url | PASS | path=/app field='https://example.com/v' search= |
| LND-10 url prefill | PASS | 'https://example.com/v' |
| LND-10 url query stripped | PASS |  |
| LND-10 text | PASS | path=/app field='https://example.com/v' search= |
| LND-10 text prefill | PASS | 'https://example.com/v' |
| LND-10 text query stripped | PASS |  |
| LND-10 title | PASS | path=/app field='' search= |
| LND-11 utm stays | PASS | / |
| LND-12 back after redirect | PASS | http://localhost:3016/privacy |
| CHR-04 noHScroll D1280 light | PASS |  |
| CHR-02 identical bars D1280 light | PASS |  |
| CHR-01 frame fixed D1280 light / | PASS | scroller=view-scroll before={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 56]} after={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 5 |
| CHR-01 frame fixed D1280 light /privacy | PASS | scroller=view-scroll before={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 56]} after={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 5 |
| CHR-01 frame fixed D1280 light /terms | PASS | scroller=view-scroll before={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 56]} after={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 5 |
| CHR-01 short page no scrollbar D1280 light | PASS | scroller=None (acceptable below 800px tall or phone) |
| CHR-04 noHScroll D1280 dark | PASS |  |
| CHR-02 identical bars D1280 dark | PASS |  |
| CHR-01 frame fixed D1280 dark / | PASS | scroller=view-scroll before={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 56]} after={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 5 |
| CHR-01 frame fixed D1280 dark /privacy | PASS | scroller=view-scroll before={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 56]} after={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 5 |
| CHR-01 frame fixed D1280 dark /terms | PASS | scroller=view-scroll before={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 56]} after={'header': [0, 0, 1280, 77], 'footer': [48, 744, 1184, 5 |
| CHR-01 short page no scrollbar D1280 dark | PASS | scroller=None (acceptable below 800px tall or phone) |
| CHR-04 noHScroll D1920 light | PASS |  |
| CHR-02 identical bars D1920 light | PASS |  |
| CHR-01 frame fixed D1920 light / | PASS | scroller=view-scroll before={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 1184, 56]} after={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 118 |
| CHR-01 frame fixed D1920 light /privacy | PASS | scroller=view-scroll before={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 1184, 56]} after={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 118 |
| CHR-01 frame fixed D1920 light /terms | PASS | scroller=None before={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 1184, 56]} after={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 1184, 56]} |
| CHR-01 short page no scrollbar D1920 light | PASS | scroller=None (acceptable below 800px tall or phone) |
| CHR-04 noHScroll D1920 dark | PASS |  |
| CHR-02 identical bars D1920 dark | PASS |  |
| CHR-01 frame fixed D1920 dark / | PASS | scroller=view-scroll before={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 1184, 56]} after={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 118 |
| CHR-01 frame fixed D1920 dark /privacy | PASS | scroller=view-scroll before={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 1184, 56]} after={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 118 |
| CHR-01 frame fixed D1920 dark /terms | PASS | scroller=None before={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 1184, 56]} after={'header': [0, 0, 1920, 77], 'footer': [368, 1024, 1184, 56]} |
| CHR-01 short page no scrollbar D1920 dark | PASS | scroller=None (acceptable below 800px tall or phone) |
| CHR-04 noHScroll D1366 light | PASS |  |
| CHR-02 identical bars D1366 light | PASS |  |
| CHR-01 frame fixed D1366 light / | PASS | scroller=view-scroll before={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 56]} after={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 5 |
| CHR-01 frame fixed D1366 light /privacy | PASS | scroller=view-scroll before={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 56]} after={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 5 |
| CHR-01 frame fixed D1366 light /terms | PASS | scroller=view-scroll before={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 56]} after={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 5 |
| CHR-01 short page no scrollbar D1366 light | PASS | scroller=None (acceptable below 800px tall or phone) |
| CHR-04 noHScroll D1366 dark | PASS |  |
| CHR-02 identical bars D1366 dark | PASS |  |
| CHR-01 frame fixed D1366 dark / | PASS | scroller=view-scroll before={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 56]} after={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 5 |
| CHR-01 frame fixed D1366 dark /privacy | PASS | scroller=view-scroll before={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 56]} after={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 5 |
| CHR-01 frame fixed D1366 dark /terms | PASS | scroller=view-scroll before={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 56]} after={'header': [0, 0, 1366, 77], 'footer': [91, 712, 1184, 5 |
| CHR-01 short page no scrollbar D1366 dark | PASS | scroller=None (acceptable below 800px tall or phone) |
| CHR-04 noHScroll P390 light | PASS |  |
| CHR-02 identical bars P390 light | PASS |  |
| CHR-01 frame fixed P390 light / | PASS | scroller=viewport before={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} after={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} scr |
| CHR-01 frame fixed P390 light /privacy | PASS | scroller=viewport before={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} after={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} scr |
| CHR-01 frame fixed P390 light /terms | PASS | scroller=viewport before={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} after={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} scr |
| CHR-01 short page no scrollbar P390 light | PASS | scroller=viewport (acceptable below 800px tall or phone) |
| CHR-04 noHScroll P390 dark | PASS |  |
| CHR-02 identical bars P390 dark | PASS |  |
| CHR-01 frame fixed P390 dark / | PASS | scroller=viewport before={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} after={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} scr |
| CHR-01 frame fixed P390 dark /privacy | PASS | scroller=viewport before={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} after={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} scr |
| CHR-01 frame fixed P390 dark /terms | PASS | scroller=viewport before={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} after={'header': [0, 0, 390, 69], 'footer': [16, 772, 358, 56]} scr |
| CHR-01 short page no scrollbar P390 dark | PASS | scroller=viewport (acceptable below 800px tall or phone) |
| CHR-08 footer links | PASS | ['/privacy', '/terms'] |
| APP-09 brand -> / | PASS | / |
| APP-02 History | PASS | /app?view=history |
| APP-02 API key | PASS | /app?view=api-key |
| APP-02 Releases | PASS | /app?view=releases |
| APP-03 Analyze | PASS | /app |
| APP-07 back/forward | PASS | ['/app?view=releases', '/app?view=api-key', '/app?view=releases'] |
| APP-02 aria-current follows | PASS | ['Releases'] |
| APP-05 unknown view | PASS | falls back to Analyze |
| APP-04 cold ?view=history | PASS |  |
| APP-04 cold ?view=api-key | PASS |  |
| APP-04 cold ?view=releases | PASS |  |
| APP-01 title | PASS | VideoLens AI |
| CHR-07 hamburger | PASS | {"expanded": "true", "menuVisible": true, "links": ["Analyze", "History", "API key", "Releases"], "bodyScroll": "clip", "afterEsc": "false", "focusBac |
| CHR-07 toggle closes | PASS |  |
| CHR-06 width sweep | PASS | [] |
| HIS-02 empty state | PASS |  |
| HIS-02 button -> Analyze | PASS |  |
| HIS-01 grid D1280 light | PASS | items=4 groups=['Today', 'Earlier this week', 'Earlier'] |
| HIS-01 grid D1280 dark | PASS | items=4 groups=['Today', 'Earlier this week', 'Earlier'] |
| HIS-01 grid D1920 light | PASS | items=4 groups=['Today', 'Earlier this week', 'Earlier'] |
| HIS-01 grid D1920 dark | PASS | items=4 groups=['Today', 'Earlier this week', 'Earlier'] |
| HIS-01 grid D1366 light | PASS | items=4 groups=['Today', 'Earlier this week', 'Earlier'] |
| HIS-01 grid D1366 dark | PASS | items=4 groups=['Today', 'Earlier this week', 'Earlier'] |
| HIS-01 grid P390 light | PASS | items=4 groups=['Today', 'Earlier this week', 'Earlier'] |
| HIS-01 grid P390 dark | PASS | items=4 groups=['Today', 'Earlier this week', 'Earlier'] |
| HIS-05 sort | PASS | {"newest": ["Alpha newest", "Bravo", "Charlie", "Delta oldest"], "oldest": ["Delta oldest", "Charlie", "Bravo", "Alpha newest"]} |
| THM-03/04 first paint dark / | PASS | data-theme at DOMContentLoaded=dark bg=rgb(14, 16, 15) |
| THM-03/04 first paint light / | PASS | data-theme at DOMContentLoaded=light bg=rgb(246, 244, 238) |
| THM-03/04 first paint dark /app | PASS | data-theme at DOMContentLoaded=dark bg=rgb(14, 16, 15) |
| THM-03/04 first paint light /app | PASS | data-theme at DOMContentLoaded=light bg=rgb(246, 244, 238) |
| THM-03/04 first paint dark /app?view=history | PASS | data-theme at DOMContentLoaded=dark bg=rgb(14, 16, 15) |
| THM-03/04 first paint light /app?view=history | PASS | data-theme at DOMContentLoaded=light bg=rgb(246, 244, 238) |
| THM-03/04 first paint dark /app?view=api-key | PASS | data-theme at DOMContentLoaded=dark bg=rgb(14, 16, 15) |
| THM-03/04 first paint light /app?view=api-key | PASS | data-theme at DOMContentLoaded=light bg=rgb(246, 244, 238) |
| THM-03/04 first paint dark /app?view=releases | PASS | data-theme at DOMContentLoaded=dark bg=rgb(14, 16, 15) |
| THM-03/04 first paint light /app?view=releases | PASS | data-theme at DOMContentLoaded=light bg=rgb(246, 244, 238) |
| THM-03/04 first paint dark /privacy | PASS | data-theme at DOMContentLoaded=dark bg=rgb(14, 16, 15) |
| THM-03/04 first paint light /privacy | PASS | data-theme at DOMContentLoaded=light bg=rgb(246, 244, 238) |
| THM-03/04 first paint dark /terms | PASS | data-theme at DOMContentLoaded=dark bg=rgb(14, 16, 15) |
| THM-03/04 first paint light /terms | PASS | data-theme at DOMContentLoaded=light bg=rgb(246, 244, 238) |
| THM-03/04 first paint dark /offline | PASS | data-theme at DOMContentLoaded=dark bg=rgb(14, 16, 15) |
| THM-03/04 first paint light /offline | PASS | data-theme at DOMContentLoaded=light bg=rgb(246, 244, 238) |
| THM-01 toggle flips and stores | PASS | light -> dark, ls=dark, name/state=['Toggle theme', None, ''] |
| THM-01 toggle accessible name | PASS | ['Toggle theme', None, ''] |
| THM-01 persists reload | PASS |  |
| THM-05 System follows OS live | PASS | dark -> light |
| THM-08 theme-color meta | PASS | content=#F6F4EE color-scheme=light |
| THM-07 corrupt value falls back | PASS | light |
| THM-02 theme choice in browser-tab menu | PASS | menu text='Analyze History API key Releases' (record where System/Light/Dark live in a tab) |
| THM-06 screenshots captured | PASS | visually reviewed D1280/P390 x light/dark for History, API key, Releases: no invisible text, borders and links visible, nothing clipped. Landing, run stages and result views checked only via the LND/RUN/RES screenshots |
| REL-01 releases list | PASS | videolens Analyze History API key Releases Releases  What changed in each version. You are on version 2.1.1.  Version 2.1.1 Latest Oct 31, 2026  Relea |
| REL-02 empty releases | PASS | videolens Analyze History API key Releases Releases  What changed in each version. You are on version 2.1.1.  No releases published yet.  VideoLens AI |
| LEG-01 /privacy | PASS | verified manually: 1 h1, header, footer, no h-scroll (harness counted 2 headers) |
| LEG-02 back link present | PASS |  |
| LEG-01 /terms | PASS | same as /privacy |
| LEG-03 back from /privacy | PASS | / |
| OFF-08 manifest | PASS | {"start_url": "/app", "display": "standalone", "share_action": "/app?share-target=1", "icons": [200, 200, 200]} |
| OFF-01 SW registered | PASS | http://localhost:3016/ |
| OFF-02 offline loads /app | PASS | videolens Analyze History API key Releases You're offline  VideoLens needs a con |
| OFF-05 privacy offline loads /privacy | PASS | 200 from SW offline |
| OFF-05 terms offline loads /terms | PASS | 200 from SW offline |
| OFF-05 root offline loads / | PASS | videolens Analyze History API key Releases  NOTES FROM SHORT VIDEO  Turn any sho |
| OFF-03 uncached route -> /offline page | FAIL | D8: unknown URL gives a bare Next 404 with no header/footer, online and offline |
| HIS-10 offline cold load history | PASS | offline reload of /app?view=history served by SW, empty-state shown (200, from SW) |
| OFF-09 API not served from cache offline | N/A | route mock answers /api; not testable in this harness |
| OFF-04 /offline renders with chrome | PASS | ['/', '/app', '/app?view=history', '/app?view=api-key', '/app?view=releases', '/app', '/app?view=history', '/app?view=api-key', '/app?view=releases',  |
| SRV-01 unreachable notice | PASS | notice=1 |
| SRV-03 notice doesn't block | PASS | submit enabled=True |
| SRV-02 recovers on focus | PASS | notice=0 |
| SRV-04 degraded capability message | PASS | videolens Analyze History API key Releases  Unavailable right now: media processing.  Details  3 free runs left. Add your own key for more.  Add key   |
| SRV-06 busy state during slow POST | PASS | submit disabled/busy=gone (record) |
| A11-07 contrast spot check light | FAIL | D10: 'Open Google AI Studio' link 4.22:1 on API key view (light) |
| A11-07 contrast spot check dark | PASS | {} |
| A11-02 landmarks/headings / | FAIL | D9: no <main> landmark on any route |
| A11-06 names on controls / | PASS | [] |
| A11-02 landmarks/headings /app | FAIL | D9: no <main> |
| A11-06 names on controls /app | PASS | [] |
| A11-02 landmarks/headings /app?view=history | FAIL | D9: no <main> |
| A11-06 names on controls /app?view=history | PASS | [] |
| A11-02 landmarks/headings /app?view=api-key | FAIL | D9: no <main> |
| A11-06 names on controls /app?view=api-key | PASS | [] |
| A11-02 landmarks/headings /app?view=releases | FAIL | D9: no <main> |
| A11-06 names on controls /app?view=releases | PASS | [] |
| A11-02 landmarks/headings /privacy | FAIL | D9: no <main> |
| A11-06 names on controls /privacy | PASS | [] |
| A11-02 landmarks/headings /terms | FAIL | D9: no <main> |
| A11-06 names on controls /terms | PASS | [] |
| A11-02 landmarks/headings /offline | FAIL | D9: no <main> |
| A11-06 names on controls /offline | PASS | [] |
| A11-04 error announced (role=alert or aria-live) | PASS | ['alert', None] |
| A11-08 reduced=False | PASS | running animations=0 scroll-behavior=auto |
| A11-08 reduced=True | PASS | running animations=0 scroll-behavior=auto |
| A11-09 zoom 200% (viewport 640x400) | PASS | {"band": 275, "nohs": true} |
| A11-09 zoom 400% (viewport 320x200) | FAIL | D12 (info): content band only 59px tall at 320x200; nothing overflows |
| A11-13 targets >= 24px (P390) | FAIL | D11: terms checkbox 20x20; footer Terms/Privacy 18px high |
| STB-03 back/forward trail | PASS | trail=['/privacy', '/app?view=releases', '/app?view=api-key', '/app', '/app?view=history', '/app', '/', '/app', '/app?view=history', '/app', '/app?vie |
| STB-04 reload keeps page | PASS |  |
| STB-06 rapid switching | PASS | 20 tab flips + 20 theme flips: no errors, no h-scroll |
| STB-08 localStorage blocked | PASS | videolens Analyze History API key Releases  3 free runs left. Add your own key for more.  Add key  N |
| STB-02 no third-party requests | PASS | only localhost:8000 (the app's own API base) |
| STB-12 security headers | PASS | recorded={} |
| STB-02 no :3005 refs | PASS |  |
| INT-16 corrupt mp4 no crash/stuck | PASS | posts=2 snippet='videolens Analyze History API key Releases Queued Reading your video  Your run is in line and starts in a moment. You can leave this  |
| INT-20 mouse copy says Drop | PASS | 'Drop an audio or video file' on desktop |
| INT-19 drop outside zone stays | PASS |  |
| INT-20 touch copy says Add | PASS | 'VideoLens AI(function(){var r=document.documentElement,q=null;try{q=window.matchMedia("(prefers-color-scheme: dark)");}catch(e){}function s(){var t;t |
| INT-21/A11-01 tab order and focus ring | PASS | order=['videolens/ring', 'Analyze/ring', 'History/ring', 'API key/ring', 'Releases/ring', 'Toggle theme/ring', 'Add key/ring', 'media-url/ring', 'Anal |
| INT-22 Enter submits once | PASS | 1 POST (rerun in isolation) |
| INT-24 double click one POST | PASS | posts=1 |
| INT-25 typed link after tab switch | PASS | value kept='' (record: kept or cleared) |
| HIS-03 search filters | PASS | ['Bravo'] |
| HIS-03 no match state | PASS | videolens Analyze History API key Releases History  Your recent analyses. Open one to read its notes again.  All Instagr |
| HIS-04 platform chips | PASS | {'Instagram': (['Delta oldest'], 'true'), 'TikTok': (['Bravo'], 'true'), 'YouTube': (['Alpha newest'], 'true'), 'Files': (['Charlie'], 'true'), 'All': |
| HIS-04 chip aria-pressed | N/A | harness read the attribute right after each click; not verified |
| HIS-07 open card and Back | PASS | opened=True url_after_back=?view=history result_still_open=0 |
| HIS-06 group headings | PASS | ['Today', 'Earlier this week', 'Earlier'] |
| HIS-06 cap of 20 | N/A | D7 withdrawn: the cap is applied on write; direct IndexedDB seeding bypasses it. Case text fixed; retest via the write path |
| HIS-15 no broken images | PASS | img with naturalWidth 0 = 0 (record: placeholder expected for corrupt data URL) |
| HIS-09 offline reopen | PASS | result shown offline=True |
| HIS-14 import runs once | PASS | videolens-history-imported=1 |
| HIS-12 IndexedDB blocked doesn't crash | PASS | page stays up and shows a 'History can't be saved...' message |

### 2026-11-02 · frontend-43 · run 2 (retest of refinement 6, HEAD b630a8d)

Production build, `next start -p 3016`, headless Chromium, `/api` mocked. Case text updated first per the lead (selectors
`main.view-scroll` / `main[data-view]`, INT-04, INT-16, RUN-06, RUN-08, RUN-13, RUN-16, OFF-03, A11-13, RES-14).

| ID | Result | Evidence |
|---|---|---|
| D1 INT-04 | PASS | both errors on one press, focus on the link, no POST; editing the link clears only its error; ticking terms clears only the terms error (either order) |
| D2 INT-16 | PASS | "This file is empty. Choose another one.", 0 requests |
| D3 RUN-06 | PASS (4 variants) | (a) mid-run reload resumes to the result; (b) reload on `?view=history` stays History; (c) reload with the API down shows Connection lost, then Retry now resumes; (d) reload after the run expired shows the expired view |
| D4 RUN-08 | PASS | poll 503s: "Server trouble" + "The server is having trouble right now…" with countdown and Retry now; network aborts: "Connection lost" |
| D5 RUN-13 | PASS | badge reads Expired, `data-run-status="expired"` |
| D6 RUN-16 | PASS (7) | 500 plain/JSON, 503 curated, 429 with Retry-After 300 ("about 5 minutes"), 429 without, 400, 422 all as specified; form usable after each |
| D8 OFF-03 | PASS | online: 404 with header and footer, one `<main>`, no h-scroll; offline: `/offline` |
| D9 A11-02 | PASS | exactly one `<main>` on all 8 routes in light and dark, plus the 404 page |
| D10 A11-07 | PASS | no contrast failures on 7 routes, light and dark (the AI Studio link included) |
| D11 A11-13 | PASS | `.terms-box` 44x44, footer links 46x44 and 38x44; clicking the box toggles the checkbox |
| D13 RES-14 | PASS | Arabic Notes: `direction: rtl` on heading, bullet and paragraph, `dir="auto"`; English stays LTR |

Note for the lead on the 18 px: those two were the **inline Terms and Privacy Policy links inside the terms sentence** (38x18 and
86x18, `display: inline`, measured with `getBoundingClientRect()` on every `a`), not the footer. My D11 row in run 1 mislabelled them.
Footer links measure 44 px. Inline links in a sentence are exempt from the WCAG 2.5.8 target-size minimum, so I treat this as no defect.

Note on (c): an offline *document* reload on bare `/app` lands on `/offline` by design (the service worker allows only
`/app?view=history` offline), so "Connection lost" is tested with the document online and the API unreachable.

**Regression (intake, runs, History) at D1366 and P390, light and dark:** 59 PASS, 6 FAIL, 2 BLOCKED in each of the four
configurations, identical across them. The six are the same harness artifacts as run 1, not app defects: INT-20 (text finder),
INT-22 (post counter carried over; passed alone in run 1), RUN-17 (route mock still answers offline; passed in isolation), HIS-04
(attribute read right after each click), HIS-06 (direct IndexedDB seeding bypasses the write-side cap), HIS-12 (assertion; the page
shows its "History can't be saved" message). RUN-R1 and RUN-R2 are still BLOCKED. No new defects.

### 2026-11-02 · frontend-43 · run 3 (six artifacts resolved, refinement 7 retest, HEAD 6bc0ac7 incl. afb41d8)

Production build, `next start -p 3016`, headless Chromium, `/api` mocked. The six run-1/2 "harness artifact" FAILs, each fixed and rerun:

| Case | Verdict | What the artifact was |
|---|---|---|
| INT-20 | PASS | the text finder looked in the wrong element; now reads the page text ("Drop an audio or video file" on mouse, "Add an audio or video file" on touch) |
| INT-22 | PASS | the mock's POST counter carried over from an earlier case; `reset()` first, then exactly 1 POST |
| RUN-17 | PASS | the route mock kept answering while "offline"; now the API is aborted: "Can't reach the server. It may be offline, or your connection dropped.", no spinner |
| HIS-04 | PASS | read `aria-pressed` only on the chip just clicked; now all chips are read after each click, exactly one is true |
| HIS-06 | PASS | seeding 25 rows straight into IndexedDB bypasses the write-side cap; with 19 seeded + 3 runs submitted through the UI, exactly 20 remain and the oldest is dropped |
| HIS-12 | PASS | assertion counted `<header>`s; with IndexedDB blocked the page shows "History can't be saved in this browser.", Analyze still works, 0 page errors |

Refinement 7 retest: **THM** all PASS: toggle flips/stores/named and persists; System/Light/Dark in the installed-shell More sheet
(Light and Dark store the value, System removes it and follows the OS, "Following your device" / "Set in this app"; the Welcome dialog
had to be dismissed first via `videolens-welcome-v1`); System follows `emulateMedia` flips live with no reload and the meta
theme-color (#0E100F / #F6F4EE) and `color-scheme` follow; a stored Light or Dark ignores OS flips; corrupt value falls back
to System with no console error; no flash on two reloads for stored Dark, stored Light, System on a dark OS and System on a light OS,
across all 8 routes plus the 404 (first-paint `data-theme` correct), and in the installed shell. **HEAD**: `node --check` passes on the
2 inline scripts of each of the 6 exported pages (`_global-error.html` has none and is not a page); no page errors on any route.
**Landing redirects** were not changed by 7 and were rerun in run 1 and 2; the head script runs clean on `/`. **WEB-429**
`Retry-After: 1800` exposed gives "You're going a bit fast. Try again in about 30 minutes."; with the header not exposed the app falls
back to the plain message. **Smoke** at P390 and D1366, light and dark, on `/`, `/app`, `/privacy`, `/offline` and the 404: 20 of 20
PASS (one `<main>`, footer, header, no horizontal scroll, theme correct, 404 status on the 404, no page errors).

Totals this run: 49 PASS (plus 20 smoke), 0 FAIL, 0 new defects.

### 2026-11-02 · frontend-43 · run 4 (refinement 8 retest, HEAD 04a9a9c)

Production build, `next start -p 3016`, headless Chromium, `/api` mocked. Browse-files expectation in INT-03 is now: enabled while the
terms are unticked; click, Enter or Space shows the terms error, focuses the checkbox (`aria-invalid`, in view) and opens no picker.

| Case | Result | Evidence |
|---|---|---|
| INT-03 Browse enabled while unticked (D1280, P390) | PASS | button enabled |
| INT-03 click (D1280, P390), Enter, Space | PASS | terms error shown, checkbox focused, `aria-invalid=true`, in view, 0 file choosers, 0 POST |
| INT-19 file drop while unticked | PASS | same error and focus, 0 POST, address unchanged |
| INT-19 text/link drag | PASS | ignored: no error, no POST, no navigation |
| INT-19 file drop while ticked | PASS | exactly 1 POST |
| INT-03 tick, then Browse | PASS | picker opens, chosen file sends exactly 1 POST; ticking clears the error |
| LND-09/10/11/12 landing redirects | PASS | `?view=` and share/url/text redirects, utm stays, back-after-redirect |
| Head script `node --check` | PASS | 2 scripts on each of 6 pages; no page errors on any route |
| `/nope` on next start | PASS | status 404, address stays `/nope`, "Open VideoLens" (`/app`) and "Go to the home page" (`/`) visible, one `<main>`, chrome present |
| OFF-03 online / offline | PASS | online: 404 with chrome; offline: `/offline` |
| Smoke P390 and D1366, light and dark | PASS | 24/24 |
| `build:mobile` | PASS | `fix-export-segments: flattened 5 segment file(s)`; `out/app/__next.app.__PAGE__.txt` is a file (2958 bytes), no `__next.app` folder |

Harness notes (not app issues): the first drop test targeted an ancestor of `.drop` (the handler is on `.drop`), so it was fixed and rerun;
the old "D8 online unknown path" assertion looks for the words "not found" and the page says "This page doesn't exist", so I judged
it by hand (404, header and footer present).

### 2026-11-02 · frontend-43 · run 5 (RUN-R1/R2 attempt)

Backend :8000 (health 200) and dev server :3005 were up at the start. Banner before: "3 free runs left. Add your own key for more."

| Case | Result | Evidence |
|---|---|---|
| RUN-R1 REAL | BLOCKED (backend killed for memory) | One POST sent; Downloading reached Done, then the page showed "Connection lost" with Normalizing at "Waiting for connection" after 306 s. The backend and :3005 were then killed for low memory (lead's report), so this is the outage, not an app defect. Not a pass: no result, no thumbnail, History row left at Processing. One free run may have been spent. |
| RUN-R2 REAL | BLOCKED (backend killed for memory) | Not attempted. |

Incidental, from the outage: the stage list showed "Waiting for connection" with a retry countdown, "Retry now" and "Stop watching", as designed.

### 2026-11-02 · videolens-65 (web QA) · run 6 (RUN-R1/R2, FREE-02b)

Real backend :8000 (HEAD d032e59), **dev server :3005** (not a production build; the lead directed it), headless Chromium 1217 from a throwaway
persistent profile, 1280x800 light. Test link: `https://www.youtube.com/watch?v=jNQXAC9IVRw` (the Instagram link needs cookies this backend lacks).
Test file: `test-15s.mp4` (testsrc 720x1280, 15 s). Banner before the first run: "3 free runs left."

| Case | Result | Evidence |
|---|---|---|
| RUN-R1 REAL | PASS | Queued 0.3 s, Downloading to 3.6 s, Normalizing 3.6-6.7 s, Uploading 6.7-12.9 s, Analyzing 12.9-22.1 s: result in about 22 s (Normalizing was NOT slow this time, about 3 s). Tabs TL;DR, Notes, Transcript (timestamped, 3 lines), On-screen ("No on-screen text was detected") all render. History row "Me at the zoo", YouTube, 0:19, thumbnail 320x240 (server image). Free runs 3 to 2. One POST, no console errors. |
| RUN-R2 REAL | PASS | Queued, "File received" Done at 1.5 s, result at about 19 s (intermediate stages not captured by the 1 s poll). Tabs: TL;DR, Notes, Transcript ("No spoken content was detected", although the file has a tone, which is fine), On-screen lists 0:00 "0" to 0:14 "14". History row "Color Bars Test Pattern with Audio Tone", Video file, 0:15, portrait poster 180x320. Free runs 2 to 1. One POST, no console errors. |
| FREE-02b (web) | PASS | Instagram link: Downloading to Failed in about 6.5 s, "This post isn't public - Instagram only serves it to signed-in viewers." Banner stayed "1 free run left" after a reload: the failed run was refunded. |
| Run 5 stuck History row to Expired | N/A | That row lived in frontend-43's throwaway profile, which was not available. Not recreated. |

Observations (not defects, reported for the lead): the failed Instagram run's History row is titled "Untitled run" with a generic "Link" label and a "Failed" badge (no platform name). The R1 Source panel shows the YouTube description verbatim, including unrelated links (the video's real description). The on-page counter I read right after the failed run was not re-read before the reload, so the stale-counter issue (refinement 9) was not exercised.

### 2026-11-02 · videolens-65 (web QA) · run 7 (refinement 9 retest, HEAD 79d69fc)

:3005 dev server (HMR, not restarted; served the new copy), headless Chromium 1217, fresh context per scenario. Items 1-6, 7b/7c, 8 and 10 used
`/api` route mocks (Python Playwright, `%TEMP%\qaweb\run7`); 7a and 9 also ran against the **real** backend :8000 (Instagram link, no Gemini spend,
free runs 3 to 3). Spot checks at 1280 light and 390 dark (screenshots in `%TEMP%\qaweb\run7`). No defects.

| # | Result | Evidence |
|---|---|---|
| 1 Stage/media copy | PASS | mp3: Queued "In line", Normalizing "Preparing your audio" (hint shown), Uploading "Sending your audio for analysis", Analyzing "Listening to your audio" (hint gone); the word "video" never appears. mp4: "Preparing / Sending / Reading your video". (A mocked file run forced into `downloading` says "Fetching it from the link first": an impossible state for a file, a mock artifact.) |
| 2 Out of free runs | PASS | Note "No free runs left today, so analyzing is paused. Add key to keep going." shown at 1280 light and 390 dark; Analyze link and Browse files both `aria-describedby="intake-blocked"` and disabled; Add key href `/app?view=api-key`, click lands on the API key tab. |
| 3 "YouTube" spelling | PASS | With `platform: "Youtube"` from the server: source card "YouTube", source toggle "Source: YouTube, jawed", Markdown export "- **Platform:** YouTube". No "Youtube" anywhere. |
| 4 Expired copy | PASS | "The server no longer has this run, and its result never reached this device." No "hour" in the page. |
| 5 Free-runs refresh | PASS | Visibility hidden then visible re-read `/api/free-runs` (3 to 2, calls 1 to 2); after a run completes and "Analyze another file", the banner shows the new count. |
| 6 "Choose the file again" | PASS | Terms ticked: the file chooser opens. Terms unticked: no chooser, the alert "Accept the media-use terms before analysis." shows and the checkbox is unchecked. |
| 7 Refund line | PASS | Mock: failed at Downloading, count unchanged: "This didn't use one of your free runs." shown (also when the refund lands after the first failed poll, and at 390 dark); failed at Analyzing with count dropped: no line. Real backend: same line, "3 free runs left" before and after. |
| 8 Privacy/Terms Back | PASS (with note) | Back is `href="/app"` on both pages, and clicking it lands on `/app` (fresh entry and from the app). It is `display:none` on the web by design (app shell only, `AppBackLink`), so a user cannot see or click it; I clicked it via script. |
| 9 Failed link title | PASS | Real failed Instagram run: History row "Instagram" / Failed / "Instagram link", not "Untitled run". |
| 10 Plain web, no update banner | PASS | /app shows no update or new-version text. |
| 11 Blocked-download advice | NOT EXERCISED | Needs a real 403/429 from a site; not triggerable here. |

Notes: the mocked Markdown export showed `NaN:NaN` timestamps because my fixture used the wrong transcript-segment field names, not an app defect.

### 2026-11-02 · videolens-65 (web QA) · run 8 (refinement 10 retest, HEAD ad39660)

:3005 dev (HMR), headless Chromium 1217, `/api` mocked by route interception (capabilities passed through to the real backend when healthy), scripts in
`%TEMP%\qaweb\run7` (t8.py). Root font 130% was applied with an injected `html{font-size:130%!important}`.

| # | Result | Evidence |
|---|---|---|
| 1 Back on /privacy and /terms | PASS | Visible at 390 and 1280, light and dark, above the title (e.g. 390: Back y=88, h1 y=132), `href="/app"`, a click lands on `/app`, no horizontal scroll (scrollWidth = innerWidth). |
| 2 5xx = unreachable | PASS with a MINOR finding | Both `/api/free-runs` and `/api/capabilities` at 500, 502 and 503: "Can't reach the server right now. You can still open past runs in History." shows (also 390 dark). Both at 400: no notice. After a healthy reply on refocus the notice clears and "3 free runs left" shows. **Finding D-R10-1:** if only ONE of the two reads fails with a 5xx and the other succeeds, no notice shows (free-runs 503 alone: 0 of 3 trials; capabilities 503 alone: 0 of 3). The two hooks share one flag and the healthy read's `noteReadResult()` clears it, so the last read wins. A full outage fails both, so this only matters for a partial failure (e.g. free-runs 500 from a Redis error). |
| 3a 320px at 130% font, no overflow | PASS (page width) | landing, /app, History, API key, Releases, Privacy, Terms, results: scrollWidth = 320 in light and dark; no nav item outside the viewport. |
| 3b Visual at 320px at 130% | FAIL (MINOR) **D-R10-2** | Results screen: the "Download .md" pill extends past its card: button x 183-364 against card right edge 299 at 320 wide (clipped, reads "Download .m"), and 183-364 at 360 wide, past the 360 viewport. Not reproducible at 100% (141-283 in a 16-304 card) or at 390/430 wide at 130%. The tab row also truncates ("Transcr…"), which looks like a scroller. Repro: 320x640 (or 360 wide), root font 130%, complete a link run, open the result. |
| 3c Normal scale 390 and 1280 | PASS | Same eight pages: no horizontal overflow, nothing clipped. |
| 4 No update popup on web | PASS | No update or new-version text on /app at 390 and 1280. |

### 2026-11-02 · videolens-65 (web QA) · run 9 (refinement 11 retest, HEAD e1f4426)

:3005 dev (HMR), headless Chromium 1217, `/api` mocked by route interception (arrival order controlled by holding and releasing each route), 130% root font via an
injected style, scripts in `%TEMP%\qaweb\run7` (t10-t12). Items 1-4 all PASS, no defects.

| # | Result | Evidence |
|---|---|---|
| 1 D-R10-1 partial outage | PASS | Free-runs 503 alone, capabilities 503 alone, and both 503: the notice shows in **both arrival orders**. A 400 on either read or both: no notice (both orders). Refocus with one read still failing: the notice stays (checked for each read). Refocus with both healthy: the notice clears and "3 free runs left" shows. Both failing, refocus still failing: stays. |
| 2a Results header at 320 and 360 (130%) | PASS | Light and dark: Download .md on its own full-width row (320: x 48-272 inside card 21-299; 360: 48-312 inside 21-339), text not clipped, page scrollWidth = viewport. |
| 2b Tab fade and chevron | PASS | End chevron + fade shown at 320/360; click scrolls the row (scrollLeft 0 to 149 at 320, to 109 at 360), start chevron scrolls back to 0. Selecting a tab by click or by arrow keys/Home/End leaves it clear of the fades (Transcript, the middle tab, ends flush against the end fade's edge, within 1 px; On-screen, Notes, TL;DR fully clear). Chevrons are `aria-hidden` with `tabindex=-1`. |
| 2c Normal scale | PASS | At 390 and 1280, 100% font, light and dark: no chevron (`data-more-*` false, `display:none`), actions on one row (same top), Download inside the card. |
| 3 History at large text | PASS | 320 and 360 at 130% (light and dark): placeholder "Search runs", fits (text 111px in 234-274px), the sort control sits below the search (sort top 349, search top 276), no page scroll, label text and accessible name "Search your runs". At 390 and 1280 at 100% the sort stays beside the search (same row) and the placeholder fits. |
| 4 Regression, normal scale | PASS | Landing, /app, History, API key, Releases, Privacy, Terms at 390 and 1280, light and dark: no horizontal overflow, nothing outside the viewport. |

### 2026-11-02 · videolens-65 (web QA) · run 10 (refinement 12 retest, HEAD 5ac8522)

:3005 dev (HMR), headless Chromium 1217, mobile context, `/api` mocked, root font set by an injected style, scripts in `%TEMP%\qaweb\run7` (t13-t15). The tab-fade
check is pixel-based: a screenshot of the solid 70% of each visible fade (chevron box masked) must equal the surface colour, at every scroll state.

| # | Result | Evidence |
|---|---|---|
| 1a Tab fades hide all tab text | PASS | 320 at 100/130/150% and 360 at 130/150%, light and dark: at the initial state, after every chevron page to the end and back, no ink in the solid part of either fade (max colour difference 0). |
| 1b Chevrons page the row | PASS | Paging reaches both ends (320@100%: 1 page, scroll 41; 320@130%: 1 page, 149; 320@150%: 2 pages, 221; 360@130%: 1 page, 109; 360@150%: 1 page, 181) and returns to 0. |
| 1c Selected tab clear of fades | PASS | Click on Transcript, On-screen, Notes, TL;DR and arrow keys/Home/End: the tab never overlaps a visible fade and stays inside the scroller (measured after the scroll animation settles, about 1 s). |
| 1d Threshold | PASS | At 100% font the end chevron shows at 340, 358 and 359 px wide and is gone (`display:none`, `data-more-end=false`) at 360, 361 and 400. |
| 2 History search | PASS | 320 and 360 at 100/115/130/150/200%: "Search runs" fits (e.g. 320@200%: 170 of 190 px), label "Search your runs", no page scroll. The sort wraps below the field when needed (320: from 115% up; 360: from 130% up) and stays beside it otherwise. 390 and 1280 at 100%: sort beside the search, unchanged. |
| 3 Menu button at 320/150% | **FAIL (MINOR) D-R12-1: yes, clipped** | Header at 320 wide, 150% font: logo 24-193, theme toggle 217-283, **Menu 295-361**, so 41 px of the 66 px button is past the 320 px edge (25 px visible). The same on /, /app, History, API key, Privacy and results, light and dark. No page scroll (the overflow is hidden). It starts at about 140% (17 px off), is 161 px off at 200%, 1 px off at 360/150% and 121 px off at 360/200%; fine at 320/130% and 390/150%. Repro: 320x640, root font 150%, open any page. Screenshots `r12-nav-320-150-*.png`. |
| 4 Normal-scale regression | PASS | 390 and 1280, light and dark: /app, results (Download inside the card, no chevrons) and History (sort beside search, placeholder fits) show no overflow. |

Observation: at 320x640 and 150% font the footer wraps and takes about 170 px, leaving a content band of about 330 px, so a forced click on the tab row can land on the footer. This is the short-viewport extreme, not reported as a defect.

### 2026-11-02 · videolens-65 (web QA) · run 11 (refinement 13 retest, HEAD a69c188)

CSS-only. Playwright, Chromium, `:3005` dev server, mocked `/api`; root font simulated with `html{font-size:N%}`. No real runs used.

| # | Item | Result | Notes |
|---|---|---|---|
| 1 | D-R12-1 header, 320/360/390 x 100-200% font, light+dark, `/`, `/app`, History, API key, Privacy, results | PASS | 180 page checks. Menu and theme toggle 44x44, 8px apart, on screen, nothing clipped, no hscroll. 320@100%: theme 208-252, menu 260-304. 320@200%: theme 192-236, menu 244-288. 360@200%: theme 232-276, menu 284-328. Nav height 68 everywhere. D-R12-1 fixed. |
| 2 | More-sheet theme control, 320/360 x 100-200% | PASS | No label wider than its segment (min slack 9.8 px), every segment >=44px tall and wide, none outside the sheet. 320: indented row at 100%, full-width row at 115-130%, stacked from 150%. 360: indented row at 100-115%, full-width row at 130%, stacked from 150%. Dark selects dark (`data-theme=dark`, radio checked) at 100% and 200% at both widths. |
| 3 | Web footer 320/360 x 130/150/200% | PASS | Footer h / band (640px viewport): 320@130% 56/495 no wrap; 320@150% 76/473 wraps; 320@200% 86/454 wraps; 360@130% 56/495; 360@150% 56/492; 360@200% 86/454 wraps. Links 44px tall everywhere. Wrap starts at 150% at 320, 200% at 360. |
| 4 | Normal-scale regression 390/1280, light+dark | PASS | `/privacy` nav and footer strips pixel-identical to the run 10 baseline at 390 light and 1280 dark (the only baselines that existed). No hscroll on `/`, `/app`, `/terms`, `/privacy` at 390/1280, light and dark. Nav 68 (390) / 76 (1280), footer 56. 390 sheet theme control indented row, 94x44 segments. Results and History were not pixel-compared; their headers were covered by item 1. |

Harness note: a first run clicked a hidden "More" match, so every sheet check timed out. That was a script bug, not an app defect; fixed and re-run.

## Changelog

- 2026-11-02 · videolens-65 (web QA) · run 11: refinement 13 retest, items 1-4 PASS (header 44px and on screen up to 200% font, theme control fits and stacks from 150%, footer links 44px, normal-scale unchanged); D-R12-1 fixed
- 2026-11-02 · videolens-65 (web QA) · run 10: refinement 12 retest, items 1, 2, 4 PASS (tab fades clean, threshold 359/360 correct); item 3 FAIL D-R12-1 (the menu button is 41 px off-screen at 320 wide, 150% font)
- 2026-11-02 · videolens-65 (web QA) · run 9: refinement 11 retest items 1-4 all PASS (D-R10-1 and D-R10-2 verified fixed), no defects
- 2026-11-02 · videolens-65 (web QA) · run 8: refinement 10 retest, items 1, 3a, 3c, 4 PASS; item 2 PASS with D-R10-1 (a partial 5xx is masked by the other healthy read); item 3b FAIL D-R10-2 (Download .md overflows its card at 320/360 wide at 130% font)
- 2026-11-02 · videolens-65 (web QA) · run 7: refinement 9 retest items 1-10 PASS, 11 NOT EXERCISED, no defects (item 8's Back link is hidden on the web by design)
- 2026-11-02 · videolens-65 (web QA) · run 6: RUN-R1 and RUN-R2 REAL both PASS on :3005 (dev), FREE-02b PASS, run 5 stuck-row check N/A
- 2026-11-02 · frontend-43 · created
- 2026-11-02 · frontend-43 · named Python Playwright as the runner (already installed, no installs)
- 2026-11-02 · frontend-43 · run 1: ran the mocked suite against the production build on :3016; logged results and 12 minor findings
- 2026-11-02 · frontend-43 · visual review of THM-06 and RES-14 done; HIS-06 case text fixed (cap applied on write, D7 withdrawn)
- 2026-11-02 · frontend-43 · run 2: retested refinement 6 (D1-D6, D8-D11, D13 all pass) and the intake/run/History regression at D1366 and P390; updated the case text
- 2026-11-02 · frontend-43 · run 3: resolved the six harness-artifact FAILs (all PASS) and retested refinement 7 (THM, head scripts, WEB-429, smoke at P390 and D1366): clean
- 2026-11-02 · frontend-43 · run 4: refinement 8 retest (Browse/drop terms behaviour, redirects, head scripts, 404, smoke, build:mobile segment fix) all PASS
- 2026-11-02 · frontend-43 · run 5: RUN-R1 started, interrupted by backend killed for memory (BLOCKED); RUN-R2 not attempted
