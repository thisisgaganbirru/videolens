# Run status pipeline view

Shows the live pipeline progress for a queued/processing run (four frames: Downloading → Normalizing → Uploading → Analyzing for a link; File received → Normalizing → Uploading → Analyzing for an upload). Renders inside the Analyze tab, above where `ResultsView` takes over once complete.

**Files**
- `frontend/components/RunStatusView.tsx` — the component. Pure/presentational: takes `status`, `stage`, `sourceKind`, `error`, `connectionLost`, `sourceLabel`, `retryInSeconds`, `retrying`, `reconnectAttempt`, `retryBusy`, `onReset`, `onRetry`, `onRetryNow` as props (all sourced from `useAnalysisRun`, see `docs/frontend/run-analysis-hook.md`).
- `frontend/components/RunStatusView.preview.tsx` — a dev-only harness rendering all 8 states (queued, each processing stage, failed, both complete variants) side by side. Not wired to any route — mount it temporarily under `app/` to visually check changes, then remove the route before committing.

**Layout (editorial Phase 2 — Progress, ProgressWeb, ProgressMobile,
ProgressFailed, ProgressLost).** `HomeScreen` owns `.run-state` (centred
column, max 56rem); the component returns a fragment: status pill → serif
`h1.run-title` → `.run-lede` → `.filmstrip` → `.source-chip` (not in failed
or lost) → either `p.run-notice` + `.run-actions` (failed / lost) or the
`.reset-link`. **design/newshots/ supersedes design/shots/** for
ProgressCaptions, ProgressUploadMobile, ProgressFailed and ProgressLostWeb. This replaces the
Terminal-era `.steps` track and `.error-block`, and the `stalled` state below.

The **filmstrip** is the progress bar: a dark strip (`--color-strip`) with
painted sprocket holes, one `li.frame` per backend stage. Below 46rem the
frames stack (holes down both sides) and the source chip spans the strip's
width; at ≥ 46rem they run four across (holes along top and bottom). The holes
are a one-hole gradient tile with `background-repeat: round`, so the run always
ends on a whole hole. File runs open on **File received** (`FILE_STEP`,
ProgressUploadMobile.png), done from the first paint: the bytes are on the
server before a run exists, and no backend stage names it.

| frame `data-state` | look | caption |
|---|---|---|
| `done` | accent-soft, check | Done |
| `active` | white, accent number/caption, `.frame-scan` sweep (one `transform`; under reduced motion it rests at ~60%), `aria-current="step"` | In progress |
| `waiting` | strip-waiting | Waiting |
| `failed` | danger-soft, 2px danger inset, X | Stopped here |
| `lost` | tint, dashed outline, wifi-off — never red | Waiting for connection |
| `missed` | as `failed`, X (captions route's Downloading frame) | Couldn't download |
| `skipped` | no fill, 1.5px dashed `--color-strip-skipped-edge`, waiting text | Skipped |

**Captions route** (`stage === "analyzing_captions"` on a link run,
ProgressCaptions.png): every download route failed, so the backend fetched the
caption track and went straight to analysis (`backend/app/application/
process_run.py` `_analyze_captions`) — normalizing and the Gemini upload never
ran. Downloading is `missed`, Normalizing and Uploading `skipped`, Analyzing
active (or failed / lost if the run stops there). Title "Reading the
captions", lede "We couldn't download the video, so we are using its captions
only. Results may have less detail.", pill stays Processing. A run of unknown
kind (reopened, no metadata yet) never gets this treatment; it falls back to
the plain Analyzing frame.

Pill (`.status[data-tone]`): Queued / Processing / Failed / Connection lost.
Titles: "Reading your video" / "Reading the captions" / "That didn't work" /
"Connection lost".

**Failed**: lede "The run stopped while <verb>. <advice>". `recoveryAdvice(stage)`:
at or after the Gemini upload it is "You can try the same link|file again."
(ProgressFailed.png's copy; the problem is on our side), at downloading "Try a
different link, or download the video and upload the file instead.", at
normalizing "Try a different link|file." The server's own error sits alone in the
`p.run-notice` card (danger border, max 40rem), and the actions sit centred
under it in `.run-actions` (ProgressFailed.png): **Try again** (ink button,
only when the hook has a source to resubmit) and **Analyze another**.
Side by side from 40rem, full-width and stacked below.

**Connection lost** (`connectionLost` from `HomeScreen`: error while queued or
processing — the same derivation as before): the current frame goes `lost`
(nothing animates), the notice reads "We can't reach the server right now.
Trying again in N seconds." with a live countdown from
`useAnalysisRun.reconnectIn`; under it **Retry now** and **Stop watching**
(ProgressLostWeb.png). The lede is the shot's: "Check your network. The page
reconnects on its own and picks up where it left off." — true: a successful reconnect resumes polling and the screen
returns to Processing by itself. It is still deliberately not danger-coloured:
the run has not failed, we have only stopped hearing about it.

**Announcements**: one `sr-only` polite region. While lost it changes once per
attempt ("Connection lost. Trying again in 8 seconds.", from
`reconnectDelayFor`); the ticking countdown is outside any live region.

**Deliberate deviations from the shots**
- "Stop watching and start another" (processing, captions; was "Stop watching and
  analyze another file" until 2026-11-14) instead of
  "Cancel": `reset()` stops polling; there is no server cancel endpoint yet (see
  the deferred item below). ProgressCaptions.png and ProgressUploadMobile.png
  already use this wording; ProgressLostWeb.png's "Stop watching" is used
  as drawn.
- ProgressFailed.png's lede says "the same link or file"; the built lede names
  the one the run actually used ("the same link" / "the same file").
- The older ProgressFailed / ProgressLost shots in design/shots/ are superseded
  by design/newshots/ and no longer followed.

**Frame labels are bold** (`.frame-label` weight 700, owner decision
2026-11-01). No frame-state rule overrides the weight, so every state
(done / active / waiting / failed / lost / missed / skipped), both themes and
the phone vertical layout get it.

**Deferred by owner decision (2026-11-01): server-side cancel.** The wording
stays "Stop watching and start another" / "Stop watching" / "Analyze
another" because the client only stops polling; the run keeps going on
the server and still spends quota. A real cancel endpoint is planned for a
later phase; when it lands, these buttons can call it and the copy can say
"Cancel". "Try again" stays a brand-new run with the same source (it does not
resume the failed one).

**Known issues**: no invented progress data — no percentage, ETA or duration,
because the backend returns none. A URL run reopened from History is recognised as one once its
status carries `source_metadata` or a link-only stage (see
`run-analysis-hook.md`); before that it shows the File received frame.
`RunStatusView.preview.tsx` still passes only the older props; it compiles
(the new props are optional) but does not show the lost countdown, retry
buttons or source chip.

**Verified (Phase 2, Playwright against the dev server, backend faked by route
interception)**: Progress 1280×860 (section 726/726, no scroll), ProgressWeb
390×900, ProgressMobile 390×918 app shell, ProgressFailed and ProgressLost at
1280×1342; plus queued (file run), each processing stage including
`analyzing_captions`, failed at downloading / normalizing / analyzing, lost in
both themes and on a phone, the countdown ticking 4→3, Retry now firing one
attempt and rescheduling at 8s, and recovery back to Processing. No page
errors, no horizontal overflow, no document scroll in any of them.

**Verified (newshots round, 2026-11-01, same harness)**: captions route at
1280×860 light/dark and 390 app; File received at 390 app light/dark and
1280; failed at 1280 light/dark and 390; lost at 390 web light/dark and 1280.
Design-vs-built pairs for ProgressCaptions, ProgressUploadMobile,
ProgressFailed and ProgressLostWeb. No page errors, no horizontal overflow.

## Expired run view (refinement 1, #7)

A run reopened from History that the server no longer had (History's
`EXPIRED_MESSAGE`) used to get the generic failed view: "The run stopped
while…" plus "Try a different link", over a guessed filmstrip. Both were
wrong: nothing was wrong with the link, and the stages were unknown.
`RunStatusView` now takes `expired`, `canRefill` and `onAnalyzeAgain` and,
for a failed + expired run, renders `ExpiredRunView`: pill "Expired", title
"This run expired", one sentence (the server keeps a run for an hour; this
one's result never reached this browser; nothing was wrong with the
link/file), **no filmstrip**, one button: "Analyze it again" (link runs, or
any run with a stored link) / "Choose the file again" (uploads). Measured at
390×844: title, pill, lede and single button as above, no `.filmstrip`;
pressing it lands on the intake with `https://youtu.be/expired1` in the field
and the terms box still ticked. Screenshots `r1-expired-390.png`,
`r1-expired-again-390.png`.

## Refinement 6 (2026-11-02)

**RUN-08.** `RunStatusView` takes `lostCause` (default `network`). When the
connection-lost state is caused by the server answering with an error
(`lostCause === "server"`), it says so: pill "Server trouble", title "The
server is having trouble", lede "It answered with an error, not a result. The
page tries again on its own and picks up where it left off.", notice "The
server is having trouble right now. Trying again in N seconds.", live region
"The server is having trouble. Trying again in N seconds.", frame caption
"Waiting for the server" with the `ServerOff` icon. Same tone, countdown,
backoff and Retry now as "Connection lost", which stays the wording when there
was no answer at all. If a retry then fails on the network, the screen switches
back to "Connection lost".

## Refinement 9 (2026-11-02)

- **Copy by stage and by media.** `progressCopy(stage, mediaKind, sourceKind)`
  in `RunStatusView.tsx` replaces the one "Reading your video / Longer files
  take more time to normalize" line. Each stage has its own title and lede;
  the normalize hint appears only while `normalizing`; "audio" or "video" is
  named only when the run is known to be one (`useAnalysisRun`'s `mediaKind`:
  the uploaded file's type, a known video host, or the server's `platform`).
  An mp3 at Analyzing now reads "Listening to your audio". Queued reads
  "In line".
- **Expired copy is true for both causes.** "The server no longer has this run,
  and its result never reached this browser." It used to say the server keeps
  runs an hour, but a restart loses them too, inside the hour. It names no
  cause, because the client cannot know which.
- **"Choose the file again" opens the picker** (expired file runs). See
  `upload-form.md`, "Refinement 9".
- **Refund line on the failed view.** `<p class="run-refund">` under the notice
  says "This didn't use one of your runs." only when a re-read of
  `/api/free-runs` proves it. See `free-runs.md`.
- **Blocked downloads (item 11).** The backend reports a temporary 403/429 block
  as "The site blocked this download for now - the video itself is fine. Try
  again in a few minutes." `recoveryAdvice` matched only on stage, so the
  next-step line said "Try a different link", which is wrong for a block. It now
  takes the error too. When a link run's message contains "site blocked this
  download", the line reads "You can try the same link again later, or download
  the video and upload the file instead." This is checked before the stage,
  because the block can land before any stage was polled. Only the text reaches
  the client (no reason code), so this is a phrase match that must stay in step
  with `_BLOCKED_DOWNLOAD` in `backend/app/infrastructure/media/ytdlp_downloader.py`.
  If that wording drifts, it falls back to the ordinary download advice.

## UX fix spec, batch c (2026-11-14)

- **Failed order.** For `mode === "failed"` only, `RunStatusView` renders
  pill, h1, lede, then `.run-notice`, `.run-refund`, `.run-actions` (Try
  again ink, Analyze another outline) and the `.filmstrip` last, so the reason
  and the way on are in the first screen on a phone (departs from
  ProgressFailed.png; owner decision). The strip and the stop block are two
  constants (`filmstrip`, `stopBlock`) so the order is one branch. Lost keeps
  the board's order (strip, then card and actions). Gaps that changed are
  `var(--space-md)`: `.run-notice[data-tone="failed"]` margin-top, and
  `.run-actions + .filmstrip` / `.run-refund + .filmstrip`.
  Measured at 412x915: notice ends at y=357, Try again at y=455.
- **Phone strip.** Below 32rem `.frame` is `min-height: 3.25rem;
  padding-block: 0.375rem` and `.frame-label` 1rem. At 320x640 the fourth
  frame is fully on screen (509 to 562, footer at 568). The strip is 270px at
  phone widths and 220px at 1280 in every stage (measured across a stage
  change), so nothing moves.
- **Expired from History.** `ExpiredRunView` (and `RunStatusView`, which
  passes it through) take `onBackToHistory`; when set, an outline "Back to
  History" follows the ink button in `.run-actions`. `HomeScreen` passes it
  only for a run opened from History.

## Changelog

- 2026-08-15 · frontend agent · ported RunStatusView to the centred .run-state pipeline; returns a fragment (.run-state > .status is a direct-child selector)
- 2026-08-15 · frontend agent (run lifecycle errors) · added `connectionLost`: a stalled pill tone, a stalled (dashed, unanimated) step state, and suppression of the "you can leave this open" note, so the view stops claiming progress once polling dies
- 2026-08-21 · main session · recovery advice now keyed on the stage the run died at rather than on sourceKind, and the dead data-error-kind attribute removed. See ../error-messaging.md
- 2026-11-01 · frontend agent · editorial Phase 2: rebuilt as the filmstrip (frame states done/active/waiting/failed/lost), serif title per state, source chip, failed/lost notice with Try again / Retry now + live reconnect countdown; Terminal-era layout/stalled sections replaced; deviations and deferred slots recorded
- 2026-11-01 · frontend agent · frame labels bold (700) in every state/theme/layout; server-side cancel recorded as deferred by owner decision (wording unchanged, Try again stays a new run)
- 2026-11-01 · frontend agent · design/newshots round: captions route (missed/skipped frames, own title + lede), File received first frame for uploads, notice card split from centred actions with no source chip in failed/lost, lost lede + "Stop watching" from ProgressLostWeb; `STAGE_ALIASES`/`FILE_STEP` TODO(design) slots closed
- 2026-11-01 · frontend agent (Phase 4) · audit only, no change: Failed, Connection lost, Captions and Upload (File received) states and frame states done/active/waiting/failed/lost/missed/skipped verified at 1366, phone web and phone app, light and dark; danger pairs recomputed (see design-direction-editorial.md)
- 2026-11-01 · frontend agent (refinement 1) · expired-run view: honest copy, no stage strip, "Analyze it again" with the link refilled
- 2026-11-02 · frontend agent (refinement 6) · RUN-08 server-trouble wording for 5xx polls (lostCause prop)
- 2026-11-02 · frontend agent (refinement 9) · stage- and media-aware progress copy (no "video" on audio, normalize hint only while normalizing); expired copy covers expiry and server loss; refund line on the failed view; blocked-download (403/429) next-step advice via a phrase match on the backend message
- 2026-11-14 · frontend agent · wording (UX fix spec batch a): "Analyze another", "Stop watching and start another", "never reached this browser", "This didn't use one of your runs."
- 2026-11-14 · frontend agent · UX fix spec batch c: failed run draws the reason, refund line and actions above the strip (lost unchanged); phone frame compaction below 32rem; `onBackToHistory` on the expired view
