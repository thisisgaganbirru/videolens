# Upload form

The "Analyze" tab's entry point: paste a public media URL, or drag/drop/browse a local file. URL is the primary path (listed first, larger emphasis) with file upload as secondary.

**Files**
- `frontend/components/UploadForm.tsx` — the form itself (no dedicated hook; this component's local state is presentational/form-validation only, not app-wide state, so it wasn't pulled into `application/`).
- `frontend/application/useSharedUrl.ts` — where the share intake went; the form only receives the result. See `share-intake.md`.
- `frontend/components/CapabilityNotice.tsx` — `CapabilityCallout`, the one-line deployment notice this form renders under the URL row. See `capability-reporting.md`.

**Client-side pre-validation** (backend re-validates authoritatively regardless):
- File: extension allowlist (`.mp3`/`.mp4`/`.mov`), `MAX_FILE_SIZE_MB` (200), and a best-effort duration check (`readMediaDuration`, via a hidden `<video>`/`<audio>` element's `loadedmetadata` event) against `MAX_DURATION_SECONDS` (180) — wrapped in try/catch since this can fail on some browsers/files, in which case it's silently skipped ("Backend performs authoritative validation").
- URL: must parse as `http:`/`https:`.

**Terms acceptance**: a checkbox, persisted in `localStorage` (`videolens-media-terms-v1`) so it stays checked across sessions once accepted. Required before either submit path proceeds — Browse is disabled until it is ticked; pressing Analyze link without it shows "Accept the media-use terms before analysis." under the terms row (`#terms-error`, refinement 4; it used to be `#intake-error`).

**Analyze link is enabled with an empty field (Phase 2).** It used to be
disabled until a URL was typed; Main.png draws it as the live green primary
with an empty field, and a greyed-out primary gives no reason. Pressing it
empty now shows "Paste a link to analyze." in `#intake-error` and focuses the
field. It is still disabled while a submit is in flight.

**The `url_download` capability notice.** The form takes an optional
`urlCapability` prop — the deployment's `url_download` row, handed down by
`HomeScreen` (which fetches the whole report once; see
`capability-reporting.md` for why the prop rather than a hook here). When that
row is `degraded` or `unavailable` a single line renders directly beneath the
URL row and above the `or` divider:

> **URL runs may fail** — yt-dlp 2026.07.04; configured cookie file is missing; login-walled sources will fail

The lead is the frontend's; everything after the dash is the backend's own
`detail`, verbatim — same rule `HistoryPanel` follows for gateway errors. The
lead exists because the row's *name* does not survive the move out of the
capability table: "the cookie file is missing" means nothing beside a URL field
without it.

Two things about it are deliberate:

- **It warns; it never blocks.** The field stays enabled at every state,
  including `unavailable`. The probe reads a yt-dlp build date and whether a
  configured cookie file exists — neither proves the link the user is about to
  paste will fail, and disabling on that evidence refuses URLs that work.
- **It is wired as `aria-describedby` on `#media-url`, not announced.** It
  reaches a screen-reader user when they focus the input, which is when it
  matters, rather than competing with the intake strip's live-region
  announcement on load. `describedBy` composes it with the existing
  `intake-error` id rather than replacing it — a validation error and a
  deployment notice can both be live at once.

**Native share-target handling**: **not here any more** — see `share-intake.md`. This component used to own the whole path (a mount-time read of `?url=`/`?text=`/`localStorage`, plus a `videolens-share` listener), which broke the moment a link was shared while a result was on screen: this component is mounted only while the run state is idle, so the event reached nobody. It now takes a `sharedUrl` prop (`{ url, receivedAt }`, a fresh object per arrival) and does one thing with it — put the link in the field and clear any error. `HomeScreen` owns the listener and has already reset the run by the time the prop lands.

The two props arrive from the same place for different reasons: `sharedUrl` is
an *instruction* (fill the field with this), `urlCapability` is a *caveat* (URL
runs may not work here). Both come from `HomeScreen` because both concern
something outside this form's mount lifetime — see `share-intake.md` and
`capability-reporting.md`.

**Layout (editorial Phase 2 — Main.png, IntakeWeb.png, IntakeFreeApp.png).**
The component now renders the white `.intake-card` itself: label "Paste a
link", `.link-row` (field + Analyze link; side by side when the card is ≥ 28rem
wide via a container query on `.link-form`, stacked below that), the
capability callout, an `or` `.divider`, the dashed `.drop` well (accent-soft
upload disc, title, "MP3, MP4, or MOV. Up to 200 MB and 3 minutes.", outlined
Browse files), and the `.terms-row`. The drop title is "Drop an audio or video
file here" on hover-capable pointers and "Add an audio or video file" under
`@media (hover: none)` — both strings are in the DOM, CSS shows one.

`HomeScreen` owns everything around the card: `.intake-layout` (one column on
a phone; ≥ 60rem two columns `minmax(0, 38.75rem) minmax(0, 28.75rem)` with a
4rem column gap — neither track has a floor, so the grid can never be wider than
its container; the panel's old `17rem` floor was removed on 2026-11-01 after an
owner report of the panel clipping at ~1086px), the eyebrow "New analysis", the serif `.intake-title`
(`text-wrap: pretty`, not `balance` — balance broke the desktop line after
"video" where the board fills it), the lede, `.cap-slot` (now a grid item of its own: first on a phone, top of the
panel column from 60rem — see `capability-reporting.md`), and the "What you
get" `aside.wyg` (TL;DR / Notes / Transcript / On-screen chips; a shorter
description per row below 60rem, as on IntakeWeb). A `TODO(phase 5)` comment
marks where the free-run banner from IntakeFreeApp.png goes.

Measured against the boards (side-by-side pairs saved during the Phase 2
pass): Main at 1280×989 fits without scrolling (section 855/855), card
412–~876 vs the board's 410–876, footer at y 932 as drawn.

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
verbatim. (The `errorKind` this used to surface as a `data-error-kind`
attribute was dropped on 2026-08-21 — nothing styled or read it; see
`../error-messaging.md`.)

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

**Form-level submit error, inside the card (owner fix 2026-11-01).** The
`useAnalysisRun` error shown at idle (server unreachable, submit rejected, a
History row that would not open) used to be a bare `.error-note` line under the
card in `HomeScreen`. It now reaches `UploadForm` as `submitError` and renders
as the card's first child, above "Paste a link": `p.intake-alert`
(`role="alert"`, danger-soft fill, hairline `--color-danger-border`, danger
ink, 0.9375rem/500; 5.6:1 light, 5.8:1 dark). Only rendered when present, so
the card does not move without it. It sets no `aria-invalid` and moves no
focus. The field-level validation line ("Paste a link to analyze.", file-type
and terms errors) is a different element and stays where it was, `.error-note`
at the foot of the card, with empty-submit still focusing the field. Both can
show at once if an old network error is still standing when a field error
fires; `submit` clears the former on the next attempt. Measured with the
backend really down at 1280 light/dark web, 1280 app, 390 web, 390 app dark:
alert first in card, no horizontal overflow. Focus after a network failure is
on `body` because the pressed button disables while sending (pre-existing,
unchanged).

**Known issues**

- The `.error-note` swap, the destroyed-URL bug and `RunStatusView`'s
  contradiction — all three previously listed here — are **fixed**; see above and
  `run-status-pipeline.md`. This component's own validation line uses the
  named `.error-note` class rather than an inline Tailwind chain (the idle
  submit note that once shared it is now `.intake-alert`, inside the card). Measured on the intake at
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
- The `url_download` notice appears *below* the analyze button rather than
  above the field. Above would put it between the `new analysis` label and the
  input, which reads as a heading for the form; below keeps it attached to the
  control it qualifies, at the cost of being read after the field on a purely
  visual scan. The `aria-describedby` wiring is what makes that safe
  non-visually.

**Tests**: none (see `run-analysis-hook.md`). The intake's failure paths have now
been exercised in a real browser (Playwright/Chromium against `next start`, all
failures *forced* via `page.route`) at 1440x900 and 390x844, light and dark:
aborted POST → connectivity wording **and the typed URL still in the field**;
429 with a JSON `detail` → the backend's sentence verbatim; slow POST → one
control labelled `sending…`, both entry points disabled, one POST after a
deliberate Enter + forced double-click; a successful 202 → results view
unchanged. Touch targets measured with `getBoundingClientRect` (Terminal
era): `analyze url` 120.9x44.0, `browse file` 122.9x44.0. Phase 2: Analyze
link is 52px tall (`.link-row .btn` min-height 3.25rem), Browse files 44px.

## Refinement 1 (2026-11-01)

- **Storage guarded (#5).** The terms flag is read/written through
  `readTermsAccepted` / `writeTermsAccepted` (try/catch; same key and the same
  stored value, `"accepted"`). Blocked storage reads as unticked and a tick is
  simply not remembered.
- **Prefill (#7, #14).** The `sharedUrl` prop is now `HomeScreen`'s
  `formPrefill`: the newer of the live share and an expired run's "Analyze it
  again" link. A share already used is dismissed when the user starts over
  ("Analyze another file", "Stop watching"), so the remounted form comes back
  empty instead of re-taking the old share. Terms stay ticked. Measured: share
  `/app?share-target=1&url=…` fills the field; after the run, "Analyze another
  file" shows an empty field with terms still ticked.

## Refinement 2 (2026-11-02)

- **`noValidate` on the link form (#4).** The field stays `type="url"` (phone
  keyboard, autofill), but the browser's "Please enter a URL." bubble no longer
  pre-empts `submitUrl`, so "Paste a link to analyze." and the `validateUrl`
  message show in `#intake-error`.
- **Which control is invalid (#4).** Errors carry a field (`url` | `terms` |
  `file`). Only `url` sets `aria-invalid` (the red `.field` state) and points
  the link input's `aria-describedby` at `intake-error`; a `terms` error marks
  the checkbox instead; a file error marks neither.
- **Touch copy (#5).** The pointer/touch swap is two generic classes,
  `.only-pointer` / `.only-touch` (`(hover: none)` in globals.css), used by the
  drop title and HomeScreen's lede: "Paste a link or drop a file." with a
  pointer, "Paste a link or add a file." on touch. They replace
  `.drop-title--pointer` / `--touch`.

## Refinement 4 (2026-11-02) — field errors sit at their field

Supersedes the `#intake-error` slot described above: there is no foot-of-card
error any more. android-66 (INT-01) found "Paste a link to analyze." under the
whole form, where the soft keyboard covered it.

- **One message slot per control**, rendered only for the field the error is
  about (`errorField`), each a `p.error-note.field-error[role=alert]`:
  - `#url-error` inside `.link-row`, directly under the field. `.link-row` is a
    grid (areas `field / error / button` stacked, `field button / error error`
    from the 28rem container query), so the message is under the field in both
    arrangements. Spacing is margins, not row-gap, so an absent error leaves no
    gap. `#media-url` gets `aria-invalid` and `aria-describedby="url-error"`
    (plus `url-capability` when that note is up).
  - `#terms-error` right under `.terms-row`; the checkbox gets `aria-invalid`,
    `aria-describedby="terms-error"`, a 2px `--color-danger` outline (INT-03)
    and focus.
  - `#file-error` right under the drop zone, described-by on Browse files.
    Focus is left alone (the picker just closed).
- **Focus and reveal.** `showError` records which control and bumps
  `errorSeq`; an effect after render focuses the control (`preventScroll`) and
  calls `revealField` (`application/useSoftKeyboard.ts`). The unit revealed is
  the control's `[data-reveal-group]` ancestor (the link form, the terms row +
  message, the drop zone + message) when it fits the visible band, else the
  control. Pressing Analyze twice on an empty field reveals it again. Every
  link error (empty or malformed) now focuses the field, not just the empty one.
- **With the keyboard open** focusing `#media-url` opens the keyboard;
  `useSoftKeyboard` re-reveals the same group once the WebView has shrunk (see
  `app-shell-layout.md`, Refinement 4). Measured with the WebView shrunk under
  the keyboard (390x844 to 514, 844x390 to 190, 360x640 to 360): field and
  message both inside the visible band, 8px apart, dock hidden.

### Landscape keyboard: the message wins (refinement 5, INT-01b)

android-66 (bundled APK, landscape, keyboard up, ~140px usable): an invalid or
empty link showed the field and Analyze, with the message ~5px from view.
Cause: `revealField` measured the window band, but the installed app scrolls
`section.view-scroll` under a fixed header, so the real band was ~83px; the
link form group did not fit, and the fallback centred the field alone. Now
`revealField` clips the band to the field's scroller and reveals, in order:
the group plus error when it fits; else field + its `role="alert"` message
(from `aria-describedby`; the capability note is ignored) centred; else that
pair aligned so the message's bottom edge is visible (4px gap), at the cost of
the field's top edge. Simulated at 844x390 shrunk to 140/160/190 and 390x844
shrunk to 420/520, light and dark, empty and invalid link: message fully inside
the section band every time (at 140: band 57-140, field 53-105, message
113-135.5).

## Refinement 6 (2026-11-02)

- **INT-04, every error at once.** The single `error`/`errorField` slot is now
  `errors: FieldErrors` (`Partial<Record<"url" | "file" | "terms", string>>`).
  `submitUrl` runs every check and shows every failure in one press: an empty
  or invalid link *and* unticked terms both render, each under its own control
  with its own `aria-describedby`/`aria-invalid`. `showErrors(next)` focuses
  and reveals the **first invalid control in DOM order** (`FIELD_ORDER`: link,
  file, terms). Editing a control clears only that control's message
  (`clearError(field)`); `clearError()` with no field clears all.
- **INT-16, empty file.** `validateFile` rejects `file.size === 0` with "This
  file is empty. Choose another one." (after the extension check), shown under
  the file control; nothing is POSTed.
- **A11-13, terms target size.** The checkbox sits in a `span.terms-box`, a
  44x44 (2.75rem) hit area with negative margins (`-0.65rem -0.75rem`) so the
  20x20 box and the text keep their exact positions (checkbox `margin` moved
  to 0; the old `0.1rem` top offset is now carried by the box's centring). It
  is inside the `<label>`, so a tap anywhere in the square toggles it — the
  harness taps all four corners at 390 and 1366 in both shells. The
  invalid-text rule became `.terms-row:has(…) > span:not(.terms-box)`.
- **RUN-16, create-run failures** are worded in the gateway
  (`infrastructure/runsGateway.ts`, `createRunFailureMessage`) and shown by the
  form's existing `.intake-alert`: a 5xx never shows its raw body ("The server
  had a problem starting this run. Try again in a moment.", except a 503 whose
  `detail` is a short user-facing sentence — the backend's curated 503s); a
  4xx keeps a usable `detail` string, else a generic line (FastAPI's 422
  arrays are not shown); a 429 reads `Retry-After` (seconds or HTTP date) as
  "You're going a bit fast. Try again in about N minutes." **The backend sends
  no `Retry-After` and does not list it in `expose_headers`** (Retry-After is
  not CORS-safelisted), so today the 429 path falls back to the backend's
  `detail`; it starts working once the backend sends and exposes the header.

## Changelog

- 2026-08-15 · frontend agent · ported UploadForm to the unboxed .intake; returns a fragment since HomeScreen supplies the wrapper
- 2026-08-15 · frontend agent (error block weight) · split HomeScreen's one error branch in two — idle demoted to an inline note in UploadForm's own error slot, poll-death promoted to a full .error-block with a start-over button inside it; requested an `.error-note` class
- 2026-08-15 · frontend agent (run lifecycle errors) · adopted `.error-note` (dropped the inlined duplicate), stopped `submit` transitioning before the 202 so a failed submit keeps the typed URL, added a scoped `sending…` busy state with a ref-guarded double-submit block, and routed submit/open errors through the shared `classifyGatewayError`
- 2026-08-21 · main session · handed the share intake to HomeScreen/useSharedUrl; this component now just takes a `sharedUrl` prop
- 2026-08-29 · frontend agent · added the optional `urlCapability` prop and the `url_download` callout under the URL row (warns, never blocks; wired as `aria-describedby` alongside `intake-error`) — see `capability-reporting.md`
- 2026-08-29 · frontend agent · reconciled the capability strip and caption-only note against the dev-side results-view restructure
- 2026-11-01 · frontend agent · editorial Phase 2: structural rebuild into `.intake-card` (link row with container-query stacking, divider, drop well with pointer/touch titles, terms row); Analyze link stays enabled when empty and explains on press; HomeScreen now owns the two-column intake layout and the "What you get" panel
- 2026-11-01 · frontend agent · intake grid: dropped the panel track's 17rem floor (both tracks minmax(0, max)), named grid areas so the service notice sits above the panel instead of between the lede and the card; 900–1280px width sweep clean in both shells and themes
- 2026-11-01 · frontend agent · owner fix: the idle submit/network error moved from a bare line under the card into the top of the intake card as `.intake-alert` (`submitError` prop, role=alert, danger-soft notice); field-level `.error-note` unchanged
- 2026-11-01 · main session · owner fix: drop zone redrawn as a compact row (icon disc left, title "Drop an audio or video file" over the limits line, Browse files pinned right; the button wraps full-width under 30rem) per the owner's intake screenshot; replaces the centred stacked well
- 2026-11-01 · main session · owner fix: the desktop intake fits one screen with no page scroll. From 60rem the top padding and headline scale with viewport height (72px / 56px only on tall windows), the card rhythm is tighter, and under 50rem of height the card padding and divider tighten further; measured with no overflow at a 1536×674 viewport (content band 540px)
- 2026-11-01 · main session · owner spec: desktop intake header fixed at a 40px top, eyebrow 13/600/0.08em with a 16px margin under it, H1 Newsreader 50/500 at line-height 1.05 and -0.02em with 20px under it, intro 18px at 1.55 in ink-2 with a 480px max-width and 24px to the card, in a 620px column; replaces the height-scaled padding and headline from the previous entry. Measured exactly in Chrome at 1536×730 with no page scroll; Newsreader is the variable 200–800 face, so 500 is a real weight, not synthesised
- 2026-11-01 · frontend agent (Phase 5b) · `blocked` prop (out of free runs, no key): Analyze link and Browse files disabled, drop refused with `dropEffect: none`, submit guarded; the link field and terms box stay usable. Note: the 1536×674 no-overflow measurement above no longer holds (587 vs 540 px without the banner); see `free-runs.md`
- 2026-11-01 · frontend agent (refinement 1) · terms storage guarded; prefill comes from HomeScreen (share or expired "analyze again"), used shares dismissed on start-over so the field clears
- 2026-11-02 · frontend agent (refinement 2) · link form `noValidate`; aria-invalid/red state only for link errors (a terms error marks the checkbox); `.only-pointer`/`.only-touch` replace the drop-title classes and fix the touch lede
- 2026-11-02 · frontend agent (refinement 4) · field errors moved next to their controls (#url-error / #terms-error / #file-error, each aria-describedby), terms checkbox gets aria-invalid + danger outline + focus, control+message revealed with revealField (INT-01, INT-03)
- 2026-11-02 · frontend agent (refinement 5) · revealField clips to the scrolling section and prefers field + error message (message bottom edge visible) over the group with Analyze in a short landscape band (INT-01b)
- 2026-11-02 · frontend agent (refinement 6) · INT-04 all field errors at once (first invalid focused); INT-16 0-byte file rejected; A11-13 44x44 terms hit area; RUN-16 create-run failure wording
