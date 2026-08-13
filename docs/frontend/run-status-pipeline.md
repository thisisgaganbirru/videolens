# Run status pipeline view

Shows the live pipeline progress for a queued/processing run (steps: download → prepare → send to Gemini → analyze, or the last three only for file uploads which skip download). Renders inside the Analyze tab, above where `ResultsView` takes over once complete.

**Files**
- `frontend/components/RunStatusView.tsx` — the component. Pure/presentational: takes `status`, `stage`, `sourceKind`, `error` as props (all sourced from `useAnalysisRun`, see `docs/frontend/run-analysis-hook.md`).
- `frontend/components/RunStatusView.preview.tsx` — a dev-only harness rendering all 8 states (queued, each processing stage, failed, both complete variants) side by side. Not wired to any route — mount it temporarily under `app/` to visually check changes, then remove the route before committing.

**Layout**: a horizontal stepper (marker + connector line per step, step title hidden below `sm`) followed by a single detail block for only the *active* (or *failed*) step's title/description/error. Deliberately not one block per step — the previous vertical list (one full title+description block stacked per step) overflowed the card's height and forced an internal scrollbar during processing, which is avoidable since nothing else needs the vertical space at that point (results aren't shown until `complete`). `getStepState`/`StepMarker` (complete/active/failed/upcoming) are unchanged from before the redesign.

**Known issue**: none identified. On very short viewports the container can still scroll (accepted tradeoff, not solved for — see `mem/20260810-run-status-pipeline-redesign.md`).

**Tests**: none (see `run-analysis-hook.md` — no frontend unit tests currently); verified via the preview harness (all 8 states) and `tsc --noEmit`.
