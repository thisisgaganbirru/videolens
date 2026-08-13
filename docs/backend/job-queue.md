# Job queue / dispatch

Decides how a run actually gets processed once accepted: in-process (local dev) or via a real background worker (production).

**Files**
- `backend/app/infrastructure/queue/job_queue.py` — `RunQueue`, implements `JobQueue`. One class, two backends — same "hybrid adapter" pattern as `RunStore` and `DailyBudget`.
- `backend/app/interface/worker/settings.py` — `WorkerSettings` (the arq worker's entrypoint config) + the `process_run` job function it registers.

**Local mode** (`queue_enabled == False`): `enqueue()` fires `asyncio.create_task(run_locally())`, which calls the injected `local_runner` (the container's bound `ProcessRunUseCase.execute`) inside a semaphore (`WORKER_MAX_JOBS`, default 2) to bound local concurrency. Note: `RunQueue` never imports `ProcessRunUseCase` directly — the use case is injected as a plain callable by `container.py`, keeping the infrastructure layer from reaching into the application layer.

**Distributed mode**: lazily creates an arq Redis pool on first use, stores a BYOK key if present (see `byok.md`), then `enqueue_job("process_run", run_id, source_url=..., source_key=..., _job_id=run_id)`. The worker process (`WorkerSettings`) picks this up separately via `arq app.worker.WorkerSettings`, and its `process_run` job function retrieves the BYOK key and calls the same `ProcessRunUseCase.execute`.

**Worker startup guard**: `WorkerSettings.on_startup` refuses to run unless both Redis and object storage are configured — a worker without S3 access can't do anything useful in distributed mode.

**Known issue**: see `run-processing.md`'s note on local mode having no persistence — this is the piece that creates that gap (an `asyncio.Task` has no durability across process restarts, unlike an arq job).

**Tests**: none directly for `RunQueue` (would need a real or mocked arq/Redis pool).
