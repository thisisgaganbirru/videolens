# Run analysis hook (useAnalysisRun)

The core client-side state machine: submit a run, poll it to completion, or open a past run from history. Everything else in the "Analyze" tab renders off this hook's state.

**Files**
- `frontend/application/useAnalysisRun.ts` - the hook.
- `frontend/infrastructure/runsGateway.ts` - `FetchRunsGateway`, what the hook actually calls.
- `frontend/components/HomeScreen.tsx` - the only consumer.

**State tracked**: `status` (`"idle" | RunStatus`), `stage`, `sourceKind` (`"file" | "url"`, used only for `RunStatusView`'s copy), `result`, `completeness` (`"full" | "captions_only"` — what the finished analysis was actually able to look at; see `results-view.md`), `sourceMetadata` (yt-dlp's platform post metadata for URL runs — title, uploader, caption, engagement counts — `null` for file uploads; see `docs/backend/media-validation.md`), `error`.

**submit(source)**: resets state, sets status to queued, calls `runsGateway.createRun`, then starts polling the returned run id. On failure, reverts to idle with the error message (unwraps `ApiError` if that's what was thrown, otherwise a generic fallback message is shown).

`completeness` is set **only alongside `result`**, in the two places a run is
observed complete (the poll tick and `openRun`), never on a `processing` tick.
It describes a finished analysis, so it is meaningless before there is one and
would otherwise sit at `full` — the wire default — while the run was still
deciding. `run.completeness ?? "full"` on read: the field is optional because a
backend older than the caption fallback omits it, and the gateway casts rather
than validates. Reset to `"full"` by `submit`, `reset` and `openRun` alongside
`result`.

**Polling**: a `setInterval` every 3 seconds calling `getRun`. Stops itself (clears the interval) once the run reaches complete or failed, or if the poll request itself throws. Cleaned up on component unmount via a `useEffect` cleanup function.

**openRun(runId)**: used by the History panel to resume viewing a past run. Clears any active poll first, optimistically sets status to processing, fetches the run once - if it's still in progress, starts polling it like a normal submit; if it's already complete or failed, just shows the result or error directly without polling.

**reset()**: returns every field to its idle value **and clears the poll interval**. Clearing it was missing until 2026-08-21, which made `reset` a lie: the interval kept calling `setStatus(run.status)` every 3 seconds, so `analyze another file` during a live run bounced back to the pipeline on the next tick. It surfaced when `HomeScreen` started calling `reset` to clear the screen for an incoming shared link (`share-intake.md`).

**Superseded requests are dropped**: `submit`, `openRun` and `reset` each bump a `generationRef` counter, and the two async ones capture it and return early if it changed while they were awaiting. Without this, a request already on the wire resolves into a screen that has moved on — a link shared mid-submit was undone a moment later by the 202 for the run the user had just abandoned. A run created by an abandoned submit still exists server-side and stays reachable from History; only the screen ignores it.

Beyond those, this is a straightforward state machine that mirrors the backend's status/stage contract exactly.

No frontend test runner is configured for this project; verification here has relied on `tsc --noEmit` plus `next build` plus manual review, not automated unit tests.

## Changelog

- 2026-08-21 · main session · made reset() clear the poll interval, and added the generation counter that drops a superseded submit/openRun response
- 2026-08-21 · main session · dropped the errorKind state, which existed only to feed a data-error-kind attribute that nothing styled or read
- 2026-08-29 · frontend agent · added `completeness` to the hook's state, set only alongside `result` and defaulted to `full` when the field is absent
- 2026-08-29 · frontend agent · reconciled the capability strip and caption-only note against the dev-side results-view restructure
