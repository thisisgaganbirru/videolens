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

Nothing worth flagging as a defect here - this is a straightforward state machine that mirrors the backend's status/stage contract exactly.

No frontend test runner is configured for this project; verification here has relied on `tsc --noEmit` plus `next build` plus manual review, not automated unit tests.

## Changelog
- 2026-08-29 · frontend agent · added `completeness` to the hook's state, set only alongside `result` and defaulted to `full` when the field is absent
