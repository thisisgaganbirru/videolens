# Job queue / dispatch

Decides how a run actually gets processed once accepted: in-process (local dev) or via a real background worker (production).

**Files**
- `backend/app/infrastructure/queue/job_queue.py` — `RunQueue`, implements `JobQueue`. One class, two backends — same "hybrid adapter" pattern as `RunStore` and `DailyBudget`.
- `backend/app/interface/worker/settings.py` — `WorkerSettings` (the arq worker's entrypoint config) + the `process_run` job function it registers.

**Local mode** (`queue_enabled == False`): `enqueue()` fires `asyncio.create_task(run_locally())`, which calls the injected `local_runner` (the container's bound `ProcessRunUseCase.execute`) inside a semaphore (`WORKER_MAX_JOBS`, default 2) to bound local concurrency. Note: `RunQueue` never imports `ProcessRunUseCase` directly — the use case is injected as a plain callable by `container.py`, keeping the infrastructure layer from reaching into the application layer.

**Distributed mode**: lazily creates an arq Redis pool on first use, stores a BYOK key if present (see `byok.md`), then `enqueue_job("process_run", run_id, source_url=..., source_key=..., _job_id=run_id)`. The worker process (`WorkerSettings`) picks this up separately via `arq app.worker.WorkerSettings`, and its `process_run` job function retrieves the BYOK key and calls the same `ProcessRunUseCase.execute`.

**Limits and the long-run job (2026-11-13)**: `enqueue(..., limits=)` takes the `MediaLimits` the API admitted. In distributed mode they go as the `limits` kwarg (`MediaLimits.to_job_arg()`: tier and numbers only, never the BYOK key), and the worker rebuilds them with `MediaLimits.from_job_arg` before calling `ProcessRunUseCase.execute(limits=...)`, so the download, probe and caption checks in the worker use the run's limits, not the worker's own standard settings. A run with `tier == signed_in_byok` is enqueued under a second job function, `process_long_run`, registered with `arq.worker.func(..., timeout=settings.long_job_timeout_seconds)`; everything else stays on `process_run` with `WORKER_JOB_TIMEOUT_SECONDS` (600). The local runner receives the same `limits` object.

**Timeout decision**: `WORKER_LONG_JOB_TIMEOUT_SECONDS` defaults to 1800 and is floored at `WORKER_JOB_TIMEOUT_SECONDS`. A 10-minute, 500 MB source needs a longer download, a re-encode roughly proportional to length, a bigger Gemini upload and a longer `ACTIVE` wait (`_wait_until_active` raised from 120 s to 300 s), and analysis over about 3x the tokens; 600 s leaves no margin for that. Every signed-in BYOK run goes on the long function, because a link's length is only known after the download. The same number sets the stale-run threshold for those runs (`GetRunUseCase`, long timeout + 120 s, chosen from `Run.media_tier`) and the long-run slot's TTL (long timeout + 120 s), so a worker that dies holding a slot frees it within that time. `RUN_TTL_SECONDS` (1 hour) is re-armed on each write and does not need to change; the frontend polls every 3 s with no overall cap.

**Deploy order**: the worker must be deployed before or with the API. An older worker does not register `process_long_run` and does not accept the `limits` kwarg.

**A job for a run that already ended (2026-11-13)**: a job can outlive its run's status. The read-time staleness check fails a run whose job is still queued (a backlog longer than the job timeout + 120 s) or still running, and an arq retry can arrive after the first attempt finished. The job is not removed from the queue; instead `ProcessRunUseCase` re-reads the run when the job starts and before normalize and Gemini, and returns without work when the run is `complete`/`failed` or gone (`run-processing.md`, "Runs that ended elsewhere"). The job then finishes normally in arq.

**Worker startup guard**: `WorkerSettings.on_startup` refuses to run unless both Redis and object storage are configured — a worker without S3 access can't do anything useful in distributed mode.

**Known issue**: see `run-processing.md`'s note on local mode having no persistence — this is the piece that creates that gap (an `asyncio.Task` has no durability across process restarts, unlike an arq job).

**Tests**: `tests/infrastructure/queue/test_job_queue_limits.py` (which function and kwargs are enqueued, with a fake pool; the key stays out of the args) and `tests/interface/worker/test_worker_settings.py` (both functions registered, the long timeout, the limits rebuilt in the worker).

## Changelog
- 2026-11-13 · backend agent · `limits` job kwarg; `process_long_run` with `WORKER_LONG_JOB_TIMEOUT_SECONDS` (1800) for signed-in BYOK runs; timeout decision, stale threshold, slot TTL and deploy order recorded
- 2026-11-13 · backend agent · a job whose run the stale-run check already failed (or whose record is gone) now does no work in the worker and cleans up
