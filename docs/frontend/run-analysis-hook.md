# Run analysis hook (useAnalysisRun)

The core client-side state machine: submit a run, poll it to completion, or open a past run from history. Everything else in the "Analyze" tab renders off this hook's state.

**Files**
- `frontend/application/useAnalysisRun.ts` - the hook.
- `frontend/infrastructure/runsGateway.ts` - `FetchRunsGateway`, what the hook actually calls.
- `frontend/components/HomeScreen.tsx` - the only consumer.

**State tracked**: `status` (`"idle" | RunStatus`), `stage`, `sourceKind` (`"file" | "url"`, used for `RunStatusView`'s copy and frame count), `sourceName`, `retrySource`, `reconnectIn`, `reconnecting`, `reconnectAttempt`, `result`, `completeness` (`"full" | "captions_only"` — what the finished analysis was actually able to look at; see `results-view.md`), `sourceMetadata` (yt-dlp's platform post metadata for URL runs — title, uploader, caption, engagement counts — `null` for file uploads; see `docs/backend/media-validation.md`), `error`.

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

**Reconnect (Phase 2, 2026-11-01).** A throwing poll no longer ends the screen.
It sets `error` (so `HomeScreen`'s `connectionLost` — error while queued or
processing — flips on) and schedules a reconnect on the backoff
`RECONNECT_DELAYS_S = [4, 8, 16, 30]` (30s repeating, never giving up: the run
may still be finishing server-side). The wait is held as a wall-clock deadline
and `reconnectIn` (whole seconds) is recomputed by a 1s ticker, so a throttled
background tab does not drift. Each attempt is one `getRun`: success clears
`error`, applies the run and resumes the 3s poll (or settles if it is now
complete/failed); failure bumps `reconnectAttempt` and schedules the next wait.
`reconnectNow()` ("Retry now") skips the countdown and is a no-op unless a
reconnect is actually pending, so a double press cannot put two requests on
the wire. `reconnecting` is true while an attempt is on the wire.
`reconnectDelayFor(attempt)` is exported so the view can announce each
attempt's wait once, without reading the ticking value. All timers are cleared
by `reset`, `submit`, `openRun` and unmount, and every callback checks the
generation counter. `scheduleReconnect` is reached through a ref (assigned in
an effect) because `startPolling` and `attemptReconnect` need it and it needs
them.

**Retry a failed run (Phase 2).** `submit` records `sourceName` (the file name,
or the URL minus scheme and `www.`) and `retrySource` (the original
`MediaSource`). `retry()` resubmits it as a brand-new run; `canRetry` is true
only when there is a source to resubmit — a run reopened from History has none,
so its failed view shows only "Analyze another file". While the resubmission is
in flight the failed view stays up with its button reading "Starting…".

**Free runs (Phase 5b).** In `submit`, a 401 with `ApiError.code === "device_token_invalid"` calls `refreshFreeRuns()` (which stores the fresh token) and sends the same `createRun` once more. A 402 `free_runs_used` calls `markFreeRunsUsed(limit, used)`, sets no error (the limit banner says it), and returns the screen to idle if the submit came from the failed view's retry. An accepted run calls `noteRunAccepted()` to re-read the count. See `free-runs.md`.

**History writes (Phase 5a).** `submit` calls `recordSubmitted` right after the 202 (even if the screen has since moved on — the run exists); `applyRun` calls `recordRunResponse(run)` for every response it applies. Both live in `application/historySync.ts` and never throw. See `run-history.md`.

**openRun(runId)** — Phase 5a: reads `historyStore.get(runId)` first. A `complete` record with a `result`, or a `failed` record, is applied straight from the store (status, result, completeness, source_metadata, sourceKind, error) with **no request** — this is what makes reopening work offline. Otherwise (still running, or no usable store) it continues as follows: used by the History panel to resume viewing a past run. Clears any active poll first, optimistically sets status to processing, fetches the run once - if it's still in progress, starts polling it like a normal submit; if it's already complete or failed, just shows the result or error directly without polling.

**reset()**: returns every field to its idle value **and clears the poll interval**. Clearing it was missing until 2026-08-21, which made `reset` a lie: the interval kept calling `setStatus(run.status)` every 3 seconds, so `analyze another file` during a live run bounced back to the pipeline on the next tick. It surfaced when `HomeScreen` started calling `reset` to clear the screen for an incoming shared link (`share-intake.md`).

**Superseded requests are dropped**: `submit`, `openRun` and `reset` each bump a `generationRef` counter, and the two async ones capture it and return early if it changed while they were awaiting. Without this, a request already on the wire resolves into a screen that has moved on — a link shared mid-submit was undone a moment later by the 202 for the run the user had just abandoned. A run created by an abandoned submit still exists server-side and stays reachable from History; only the screen ignores it.

Beyond those, this is a straightforward state machine that mirrors the backend's status/stage contract exactly.

**`sourceKind` for reopened runs (fixed Phase 3, 2026-11-01).** The backend
now stores `source_kind` (`"link" | "file"`) on every new run and returns it on
both `GET /api/runs` and `GET /api/runs/{id}`. It is the authority:
`openRun(runId, sourceKindHint?)` seeds `sourceKind` from the History
summary's `source_kind` (so the right frames show before the first response),
and `applyRun` sets it from the detail response's `source_kind` when present —
in either direction. Only when `source_kind` is null/absent (runs stored before
the field existed) does the old heuristic apply: `source_metadata` or a
`downloading` / `analyzing_captions` stage → `"url"`, never back. The residual
known issue is therefore limited to legacy link runs with no metadata reopened
after the download stage.

No frontend test runner is configured for this project; verification here has relied on `tsc --noEmit` plus `next build` plus manual review, not automated unit tests.

## Expired runs (refinement 1, #7)

`openRun` sets `expired` (and `againUrl`) when the History record's `error` is
`EXPIRED_MESSAGE` (`historySync.ts`), i.e. the server forgot the run before its
result reached this browser. `againUrl` is `record.source_url` (new optional
`HistoryRecord` field, written by `recordSubmitted` for link runs; IndexedDB
only, nothing new is sent to the server), else `source_metadata.source_url`.
`submit`, `reset` and `openRun` clear it. `HomeScreen` turns it into the
expired view and an "Analyze it again" that returns to the intake with the
link filled (see `run-status-pipeline.md`).

### A 404 on any path means expired (refinement 3, #1)

Before this, only `bootHistory`'s startup reconcile turned a 404 into
"expired". A server restart mid-run (in-memory store) left the live screen on
"Connection lost" forever (the poll and every reconnect treated the 404 as a
network blip) and a reopen from History showed the intake with a bare
"Run not found." while the row stayed "Processing".

Now `historySync.isRunGone(err)` (`ApiError` with `status === 404`) is checked
on all three paths in the hook, and each calls `expireRun(runId, generation,
knownUrl)`:

| Path | Condition | `knownUrl` |
|---|---|---|
| `startPolling` catch | any 404 | `liveUrlRef` (the link submitted in this session, else null) |
| `attemptReconnect` catch (also "Retry now") | any 404 | same |
| `openRun` server fallback | 404 **and** this browser has a History record for the id | `record.source_url ?? source_metadata.source_url` |

`expireRun` stops every timer, clears the reconnect state, sets `status:
"failed"`, `error: EXPIRED_MESSAGE` and `expired`, then awaits
`historySync.recordExpired(runId)` (upserts `failed` + `EXPIRED_MESSAGE`, the
same write the startup reconcile now uses, and resolves to the stored link).
If the caller had no link but History has one, `againUrl` is filled in when
the write lands. File runs get the expired view's "Choose the file again".
A 404 for an id this browser has never seen keeps the old idle + "Run not
found." behaviour. Network errors and 5xx keep the reconnect countdown.

## Changelog

- 2026-08-21 · main session · made reset() clear the poll interval, and added the generation counter that drops a superseded submit/openRun response
- 2026-08-21 · main session · dropped the errorKind state, which existed only to feed a data-error-kind attribute that nothing styled or read
- 2026-08-29 · frontend agent · added `completeness` to the hook's state, set only alongside `result` and defaulted to `full` when the field is absent
- 2026-08-29 · frontend agent · reconciled the capability strip and caption-only note against the dev-side results-view restructure
- 2026-11-01 · frontend agent · Phase 2: reconnect-with-countdown after a failed poll (4/8/16/30s backoff, wall-clock deadline, `reconnectNow`), `retry()`/`canRetry` resubmitting the original source, `sourceName` for the progress chip
- 2026-11-01 · frontend agent · `applyRun` infers `sourceKind: "url"` from `source_metadata` or a link-only stage, so a reopened link run no longer gets the upload-only File received frame; known issue narrowed
- 2026-11-01 · frontend agent (Phase 3) · `source_kind` from the summary/detail is now authoritative for `sourceKind` (`openRun` takes a hint; `applyRun` honours the detail); heuristic kept as the legacy fallback
- 2026-11-01 · frontend agent (Phase 5a) · `submit`/`applyRun` file runs into the browser History (`historySync.ts`); `openRun` reopens complete/failed runs from IndexedDB with no network, falling back to the server only when the record lacks a result
- 2026-11-01 · frontend agent (Phase 5b) · `submit` retries once on 401 `device_token_invalid`, marks the limit on 402 `free_runs_used` (no error line; back to idle from a failed-view retry), and refreshes the free-run count after a 202
- 2026-11-01 · frontend agent (refinement 1) · `expired` / `againUrl` for runs the server forgot; `source_url` stored on submit (IndexedDB only)
- 2026-11-02 · frontend agent (refinement 3) · a 404 on the live poll, a reconnect or openRun's server fallback now expires the run (History row failed + EXPIRED_MESSAGE, expired view) instead of "Connection lost" / "Run not found."; `liveUrlRef` for the link
