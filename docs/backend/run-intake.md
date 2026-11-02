# Run intake (create a run)

Accepts a media source (file or URL) from `POST /api/runs`, applies the intake business rules, and schedules the run for background analysis. Returns immediately with `{run_id, status: "queued"}`.

**Files**
- `backend/app/application/create_run.py` — `CreateRunUseCase`, the whole flow.
- `backend/app/interface/api/routes.py` — the `create_run` route; thin, just extracts the `X-Gemini-Api-Key` header and calls the use case.
- `backend/app/interface/api/error_handlers.py` — maps the domain errors below to HTTP status codes.
- `backend/app/domain/errors.py` — `TermsNotAcceptedError` (400), `InvalidSourceError` (400), `DeviceTokenInvalidError` (401, `code: device_token_invalid`), `FreeRunsExhaustedError` (402, `code: free_runs_used`), `QuotaExceededError` (503), `RunSchedulingError` (503), `MediaValidationError` (400).

**Rules enforced, in order**
1. `accept_terms` must be true, or `TermsNotAcceptedError`.
2. Exactly one of `file`/`url` must be given, or `InvalidSourceError` (and the uploaded file, if any, is explicitly closed before raising).
3. `_admit`: if no BYOK key was supplied and free runs are enabled, a valid `X-Device-Token` is required (`DeviceTokenInvalidError`) and one free run is taken from the device and IP counters (`FreeRunsExhaustedError` when either is spent). See `free-runs.md`. Then, still only without a BYOK key, the daily spend cap (`SpendCap.try_consume()`) must allow it, or `QuotaExceededError`. Any failure from here on refunds the free run. Before `_accept`, the free run is held against the `run_id` (`FreeRunAllowance.hold`) so `ProcessRunUseCase` can hand it back if the link later fails to download; a failed intake drops that hold before refunding.
4. If a file was given: saved to disk, duration-capped via `MediaProcessor.enforce_duration_cap`. In distributed mode (`distributed=True`, i.e. `queue_enabled`), the file is immediately uploaded to S3 and the local copy deleted — a different process (the worker) will handle it.
5. The run record is created (`RunRepository.create`) with `source_kind` (`"file"`/`"link"`) and, for uploads, the extension-derived `platform` (`audio_file`/`video_file`) and the probed `duration_seconds` returned by `enforce_duration_cap` — never the original filename. Then handed to `JobQueue.enqueue`.

**Cleanup on failure**: `MediaValidationError` triggers `cleanup_run_dir` and re-raises as-is. Any other exception also cleans up, deletes the uploaded S3 object if one was created, and re-raises as `RunSchedulingError` (masks the real cause from the caller).

**Known issue**: if `queue.enqueue()` throws (e.g. Redis unreachable) *after* `RunRepository.create()` already succeeded, the run record is never rolled back — it's left permanently in `QUEUED` status with nothing ever going to process it. Not currently handled; would need either a compensating delete or a TTL-based sweep.

**Tests**: `backend/tests/application/test_create_run.py`, using in-memory fakes from `backend/tests/application/fakes.py` (covers all 5 rules above plus local vs. distributed file handling).

## Changelog
- 2026-11-01 · backend agent (Phase 3) · intake records `source_kind`, file `platform` and probed duration on the run
- 2026-11-01 · backend agent (Phase 5b) · source check now precedes the spend cap; added the free-run admission step and its refund-on-failure
- 2026-11-02 · backend agent (free-run download refund) · intake now holds the free run per `run_id` for the download-failure refund
