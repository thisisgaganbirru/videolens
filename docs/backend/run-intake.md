# Run intake (create a run)

Accepts a media source (file or URL) from `POST /api/runs`, applies the intake business rules, and schedules the run for background analysis. Returns immediately with `{run_id, status: "queued"}`.

**Files**
- `backend/app/application/create_run.py` — `CreateRunUseCase`, the whole flow.
- `backend/app/interface/api/routes.py` — the `create_run` route; thin, just extracts the `X-Gemini-Api-Key` header and calls the use case.
- `backend/app/interface/api/error_handlers.py` — maps the domain errors below to HTTP status codes.
- `backend/app/domain/errors.py` — `TermsNotAcceptedError` (400), `InvalidSourceError` (400), `QuotaExceededError` (503), `RunSchedulingError` (503), `MediaValidationError` (400).

**Rules enforced, in order**
1. `accept_terms` must be true, or `TermsNotAcceptedError`.
2. If no BYOK key was supplied, the daily spend cap (`SpendCap.try_consume()`) must allow it, or `QuotaExceededError`. A BYOK key skips this check entirely — `try_consume()` is never called.
3. Exactly one of `file`/`url` must be given, or `InvalidSourceError` (and the uploaded file, if any, is explicitly closed before raising).
4. If a file was given: saved to disk, duration-capped via `MediaProcessor.enforce_duration_cap`. In distributed mode (`distributed=True`, i.e. `queue_enabled`), the file is immediately uploaded to S3 and the local copy deleted — a different process (the worker) will handle it.
5. The run record is created (`RunRepository.create`), then handed to `JobQueue.enqueue`.

**Cleanup on failure**: `MediaValidationError` triggers `cleanup_run_dir` and re-raises as-is. Any other exception also cleans up, deletes the uploaded S3 object if one was created, and re-raises as `RunSchedulingError` (masks the real cause from the caller).

**Known issue**: if `queue.enqueue()` throws (e.g. Redis unreachable) *after* `RunRepository.create()` already succeeded, the run record is never rolled back — it's left permanently in `QUEUED` status with nothing ever going to process it. Not currently handled; would need either a compensating delete or a TTL-based sweep.

**Tests**: `backend/tests/application/test_create_run.py`, using in-memory fakes from `backend/tests/application/fakes.py` (covers all 5 rules above plus local vs. distributed file handling).
