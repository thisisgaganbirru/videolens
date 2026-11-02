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
only when the hook has a source to resubmit) and **Analyze another file**.
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
- "Stop watching and analyze another file" (processing, captions) instead of
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
stays "Stop watching and analyze another file" / "Stop watching" / "Analyze
another file" because the client only stops polling; the run keeps going on
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
one's result never reached this device; nothing was wrong with the
link/file), **no filmstrip**, one button: "Analyze it again" (link runs, or
any run with a stored link) / "Choose the file again" (uploads). Measured at
390×844: title, pill, lede and single button as above, no `.filmstrip`;
pressing it lands on the intake with `https://youtu.be/expired1` in the field
and the terms box still ticked. Screenshots `r1-expired-390.png`,
`r1-expired-again-390.png`.

## Changelog

- 2026-08-15 · frontend agent · ported RunStatusView to the centred .run-state pipeline; returns a fragment (.run-state > .status is a direct-child selector)
- 2026-08-15 · frontend agent (run lifecycle errors) · added `connectionLost`: a stalled pill tone, a stalled (dashed, unanimated) step state, and suppression of the "you can leave this open" note, so the view stops claiming progress once polling dies
- 2026-08-21 · main session · recovery advice now keyed on the stage the run died at rather than on sourceKind, and the dead data-error-kind attribute removed. See ../error-messaging.md
- 2026-11-01 · frontend agent · editorial Phase 2: rebuilt as the filmstrip (frame states done/active/waiting/failed/lost), serif title per state, source chip, failed/lost notice with Try again / Retry now + live reconnect countdown; Terminal-era layout/stalled sections replaced; deviations and deferred slots recorded
- 2026-11-01 · frontend agent · frame labels bold (700) in every state/theme/layout; server-side cancel recorded as deferred by owner decision (wording unchanged, Try again stays a new run)
- 2026-11-01 · frontend agent · design/newshots round: captions route (missed/skipped frames, own title + lede), File received first frame for uploads, notice card split from centred actions with no source chip in failed/lost, lost lede + "Stop watching" from ProgressLostWeb; `STAGE_ALIASES`/`FILE_STEP` TODO(design) slots closed
- 2026-11-01 · frontend agent (Phase 4) · audit only, no change: Failed, Connection lost, Captions and Upload (File received) states and frame states done/active/waiting/failed/lost/missed/skipped verified at 1366, phone web and phone app, light and dark; danger pairs recomputed (see design-direction-editorial.md)
- 2026-11-01 · frontend agent (refinement 1) · expired-run view: honest copy, no stage strip, "Analyze it again" with the link refilled
