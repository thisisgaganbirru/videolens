# Upload form

The "Analyze" tab's entry point: paste a public media URL, or drag/drop/browse a local file. URL is the primary path (listed first, larger emphasis) with file upload as secondary.

**Files**
- `frontend/components/UploadForm.tsx` — the form itself (no dedicated hook; this component's local state is presentational/form-validation only, not app-wide state, so it wasn't pulled into `application/`).
- `frontend/application/useSharedUrl.ts` — where the share intake went; the form only receives the result. See `share-intake.md`.

**Client-side pre-validation** (backend re-validates authoritatively regardless):
- File: extension allowlist (`.mp3`/`.mp4`/`.mov`), `MAX_FILE_SIZE_MB` (200), and a best-effort duration check (`readMediaDuration`, via a hidden `<video>`/`<audio>` element's `loadedmetadata` event) against `MAX_DURATION_SECONDS` (180) — wrapped in try/catch since this can fail on some browsers/files, in which case it's silently skipped ("Backend performs authoritative validation").
- URL: must parse as `http:`/`https:`.

**Terms acceptance**: a checkbox, persisted in `localStorage` (`videolens-media-terms-v1`) so it stays checked across sessions once accepted. Required before either submit path is enabled.

**Native share-target handling**: **not here any more** — see `share-intake.md`. This component used to own the whole path (a mount-time read of `?url=`/`?text=`/`localStorage`, plus a `videolens-share` listener), which broke the moment a link was shared while a result was on screen: this component is mounted only while the run state is idle, so the event reached nobody. It now takes a `sharedUrl` prop (`{ url, receivedAt }`, a fresh object per arrival) and does one thing with it — put the link in the field and clear any error. `HomeScreen` owns the listener and has already reset the run by the time the prop lands.

**Layout** (Terminal redesign — see `design-direction-terminal.md`): **no
surface, no frame, no card.** It sits optically centred in `.home-center`,
capped by `.intake` (34rem): a `.row` holding the URL `.field` + primary
button, an `or` `.divider`, then the dashed `.drop` zone. Structure comes from
rules and alignment. Do not wrap it in a bordered box.

**The component returns a fragment** — `HomeScreen` already supplies the
`.home-center > .intake > .card-label` chain (styled with `--color-accent` green to match brand accenting), so re-wrapping would double-nest
it.

State hooks: `.drop[data-dragging="true"]` for drag-over,
`.field[aria-invalid="true"]` for validation failure.

## The in-flight state, and why the form no longer unmounts on submit

`useAnalysisRun.submit` used to set `status: "queued"` **before** awaiting
`createRun`. That transition unmounts the `status === "idle"` branch and with it
this component's local `url` state, so a rejected submit came back to an *empty*
field — "try again" meant "retype the URL". It was also a claim the server had
not made yet: for a file upload the pipeline sat there pulsing "normalizing"
while the bytes were still leaving the browser.

The hook now changes `status` exactly once, when the 202 lands. The intervening
moment is carried by a new `submitting` flag, which `HomeScreen` passes down as
this component's `submitting` prop:

- **Nothing is claimed.** No pipeline, no "queued" — the intake is still on
  screen because the run does not exist yet.
- **The form stays mounted**, so `url` survives a failure. This is the fix; the
  rest is what makes it feel right.
- **No double-submit window.** `busy = disabled || submitting` disables the URL
  field, both buttons and the terms checkbox, and the drop handler returns early
  while busy. The authoritative guard is a ref in the hook (a ref, not state:
  the second call can arrive in the same tick, before a re-render). Verified by
  firing Enter *and* a forced click during a deliberately slow submit — one
  POST.
- **A successful submit does not feel slower.** The pressed control relabels to
  `sending…` with `aria-busy` immediately. Only the pressed one: `pendingKind`
  records whether the URL button or the browse button started it, because
  "sending…" on both reads as two things happening at once.

**Errors are now honest about transport.** `submit`'s catch runs the shared
`classifyGatewayError` (`application/gatewayError.ts`, lifted out of
`useRunHistory`), so a backend that is *down* says "Can't reach the server…"
instead of "Could not submit media." — the latter is now only the
genuinely-unknown fallback. A server that answered shows its own `detail`
verbatim. `HomeScreen` puts the resulting `errorKind` on `data-error-kind`,
matching `HistoryPanel`.

## Where the Analyze tab's errors land

`useAnalysisRun` exposes one `error` string for three different situations, and
until 2026-08-15 all three rendered as the same centred `.error-block` parked at
the bottom of the section — the app's loudest object, carrying a single bare
`<p>` and the `p:last-of-type` margin that the locked mockup reserves for a
retry button that wasn't there. Split by what the user is actually looking at:

- **`status === "idle"` + error** — the submit was rejected (`submit`'s catch)
  or a history row would not open (`openRun`'s catch). The intake is back on
  screen and pressing the same control again *is* the recovery, so this now
  renders **inside `.intake`, below `UploadForm`**, as a one-line note in the
  same slot `UploadForm` puts its own client-side validation errors
  (`UploadForm.tsx:254`). `role="alert"`, since the user just pressed a button
  and something has to say it failed.
- **`status` queued/processing + error** — polling threw, so `useAnalysisRun`
  cleared its interval. The pipeline above is frozen and nothing on the screen
  will ever change again. That is a real full stop, so it keeps `.error-block`
  and is given what the block was drawn for: a `<strong>` lead, an explanation,
  and a `start over` button **inside** the block. The spec's reserved
  `p:last-of-type` margin is therefore the measured 24px gap above that button
  rather than dead space, and no `mb-0` cancel is needed. The block moved inside
  `.run-state`, and it *replaces* the usual `.reset-link` for this state — two
  ways to start over is one too many, and `.btn` is the one that gets a 44px
  target under `pointer: coarse` (measured 115.4 x 66.8).
- **`status === "failed"`** — untouched. `RunStatusView` owns that block.

**Known issues**

- The `.error-note` swap, the destroyed-URL bug and `RunStatusView`'s
  contradiction — all three previously listed here — are **fixed**; see above and
  `run-status-pipeline.md`. Both the idle note (`HomeScreen`) and this
  component's own validation line now use the named `.error-note` class rather
  than two copies of the same inline Tailwind chain. Measured on the intake at
  390px: **6.89:1** light / **6.99:1** dark against paper, at 11.84px.
- At 390x664 the promoted block's `start over` button sits ~19px below the fold
  and the box is clipped by the footer band. The content band does scroll and
  the button was clicked successfully in both themes, but there is no scroll
  affordance. Not a regression (the old block was below the fold too). Partially
  relieved now that the pipeline no longer renders its pending note in this
  state, but not measured again at 664px.
- **`openRun` still transitions optimistically.** Opening a run from History
  sets `status: "processing"` before the GET resolves, so for one poll's worth of
  time the pipeline shows a fabricated first step. Left as-is deliberately: the
  alternative is a flash of the empty intake form while the fetch is in flight,
  which is worse. Unlike `submit` there is no user input at risk.
- The two lucide icons (`Link2`, `UploadCloud`) were dropped — the locked
  intake markup carries no icons.
- The terms checkbox has **no mockup counterpart**, so it has no locked
  reference; it's styled as the quietest possible element under the drop zone
  and is the one part of this view without a design source.
- The URL label is `sr-only` (the `.card-label` above carries the context), but
  the `htmlFor`/`id` association is intact and the error is wired via
  `aria-describedby`.
- Best-effort duration check as documented above.

**Tests**: none (see `run-analysis-hook.md`). The intake's failure paths have now
been exercised in a real browser (Playwright/Chromium against `next start`, all
failures *forced* via `page.route`) at 1440x900 and 390x844, light and dark:
aborted POST → connectivity wording **and the typed URL still in the field**;
429 with a JSON `detail` → the backend's sentence verbatim; slow POST → one
control labelled `sending…`, both entry points disabled, one POST after a
deliberate Enter + forced double-click; a successful 202 → results view
unchanged. Touch targets measured with `getBoundingClientRect`: `analyze url`
120.9x44.0, `browse file` 122.9x44.0.

## Changelog

- 2026-08-15 · frontend agent · ported UploadForm to the unboxed .intake; returns a fragment since HomeScreen supplies the wrapper
- 2026-08-15 · frontend agent (error block weight) · split HomeScreen's one error branch in two — idle demoted to an inline note in UploadForm's own error slot, poll-death promoted to a full .error-block with a start-over button inside it; requested an `.error-note` class
- 2026-08-15 · frontend agent (run lifecycle errors) · adopted `.error-note` (dropped the inlined duplicate), stopped `submit` transitioning before the 202 so a failed submit keeps the typed URL, added a scoped `sending…` busy state with a ref-guarded double-submit block, and routed submit/open errors through the shared `classifyGatewayError`
- 2026-08-21 · main session · handed the share intake to HomeScreen/useSharedUrl; this component now just takes a `sharedUrl` prop
