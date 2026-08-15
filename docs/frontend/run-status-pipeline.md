# Run status pipeline view

Shows the live pipeline progress for a queued/processing run (steps: download → prepare → send to Gemini → analyze, or the last three only for file uploads which skip download). Renders inside the Analyze tab, above where `ResultsView` takes over once complete.

**Files**
- `frontend/components/RunStatusView.tsx` — the component. Pure/presentational: takes `status`, `stage`, `sourceKind`, `error`, `connectionLost` as props (all sourced from `useAnalysisRun`, see `docs/frontend/run-analysis-hook.md`).
- `frontend/components/RunStatusView.preview.tsx` — a dev-only harness rendering all 8 states (queued, each processing stage, failed, both complete variants) side by side. Not wired to any route — mount it temporarily under `app/` to visually check changes, then remove the route before committing.

**Layout** (Terminal redesign — see `design-direction-terminal.md`): a centred
single column (`.run-state`), *not* the two-column workspace — there's no
source metadata to show yet mid-run. A `.status` pill sits above a `.steps`
grid of equal-width `.step` tracks joined by a connector rule. Four labelled
tracks don't fit a phone, so they stack to a vertical pipeline below 32rem.
The failed state renders `.error-block`.

**The component returns a fragment, not a wrapper.** `globals.css` styles
`.run-state > .status` as a *direct-child* selector, so an intervening
`<section>` silently kills the flex gap. `HomeScreen` owns the `.run-state`
element.

**State encoding**: `.status[data-tone="processing"|"failed"]` (no `data-tone`
= complete); `.step[data-status="done"|"active"]`, with neither meaning
upcoming. Failed marks prior steps done and nothing active, so the accent pulse
never contradicts a red pill. Motion is the shared `pip-pulse`, already disabled
under `prefers-reduced-motion`.

**No retry button in the error block** — `HomeScreen` renders the reset link
beneath it; the mockup's retry button would duplicate that control.

## `connectionLost` — the stalled state

If the poll throws, `useAnalysisRun` clears its interval. Nothing on this screen
will ever change again — but the view used to carry on pulsing an `active` step
and saying "Longer files take more time to normalize. **You can leave this
open.**" Both statements are false the instant the interval dies: nothing is
progressing, and leaving it open achieves nothing.

`HomeScreen` computes `connectionLost = Boolean(error) && (status === "queued"
|| status === "processing")` — which is exactly "the poll's catch fired", since
`submit` now stays on idle until the server answers and `openRun` returns to
idle on failure. It is the *same* flag that gates the `.error-block`, so the two
treatments cannot disagree. Passing it flips three things:

| | running | stalled |
| --- | --- | --- |
| pill | `data-tone="processing"`, label `processing`/`queued`, pip pulsing | `data-tone="stalled"`, label `stalled`, pip static |
| current step | `data-status="active"`, accent fill, `pip-pulse`, `aria-current="step"` | `data-status="stalled"`, dashed muted mark, no fill, no animation, no `aria-current` |
| below the steps | `.pending-note` "you can leave this open" | **nothing** — the caller's `.error-block` follows |

**Why `stalled` and not `failed`.** The run has not failed; we have only stopped
hearing about it, and it may well still be finishing on the server (which is what
the block below says). So the pill is the processing pill with its claim
withdrawn — same outline, no fill, muted ink — and is deliberately *not*
danger-coloured. The `.error-block` directly beneath is the one thing on this
screen allowed to carry danger ink. The dashed step mark is the drop zone's
"not settled yet" idiom, reused rather than invented.

**One error treatment, one recovery control.** The pending note gives way (not
the block): the block is the thing with the explanation and the `start over`
button, and a note advising patience directly above a box saying it is over
would be two screens fighting. `HomeScreen` already swaps its `.reset-link` for
the block's own button in this state, so the total is exactly one control.
`RunStatusView`'s `aria-live="polite"` region also goes silent while stalled —
the block is `role="alert"`, and an assertive alert plus a polite status saying
the same thing is one announcement too many.

**Known issues**: no invented progress data — no percentage, ETA, or duration,
because the backend returns none. Stage announcements go to an `sr-only` polite
live region. On very short viewports the container can still scroll (accepted
tradeoff — see `mem/20260810-run-status-pipeline-redesign.md`).

**Tests**: none (see `run-analysis-hook.md` — no frontend unit tests currently);
verified via the preview harness (now 10 states, including the stalled one) and
`tsc --noEmit`. The stalled state has also been forced in a real browser
(Playwright: 202 accepted, then the polling GET aborted) at 1440x900 and 390x844
in both themes — 0 `active` steps, 1 `stalled` step, `animation-name: none` on
the pip, 0 occurrences of "You can leave this open", 0 `.pending-note` in
`.run-state`, 0 `.reset-link`, 1 `start over` (115.4x44.0 on touch), no
horizontal overflow, and the button really returns to the intake. Contrast
against paper: pill 5.26:1 / 5.53:1, stalled step label 10.8:1 / 10.83:1.

## Changelog

- 2026-08-15 · frontend agent · ported RunStatusView to the centred .run-state pipeline; returns a fragment (.run-state > .status is a direct-child selector)
- 2026-08-15 · frontend agent (run lifecycle errors) · added `connectionLost`: a stalled pill tone, a stalled (dashed, unanimated) step state, and suppression of the "you can leave this open" note, so the view stops claiming progress once polling dies
