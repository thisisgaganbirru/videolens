# Object storage (S3-compatible)

Temporary storage for uploaded source media in distributed mode, so the worker process (different machine/container than the API process) can retrieve it.

**Files**
- `backend/app/infrastructure/storage/s3_object_store.py` — `S3ObjectStore`, implements `ObjectStore`.

**When it's used**: only when `distributed=True` (i.e. `queue_enabled`, i.e. `REDIS_URL` set). `CreateRunUseCase` uploads under a size-cap-and-extension-validated file, in local mode the file just stays on the API process's local disk and `saved_path`/`run_dir` are passed straight to the local runner instead.

**Key layout**: `runs/{run_id}/source{ext}` — deleted by `ProcessRunUseCase` in its `finally` block after processing (success or failure), and by `CreateRunUseCase` if enqueueing fails after the upload already happened.

**Enabled check**: `object_storage_enabled` (a `Settings` property) requires all four of `S3_ENDPOINT_URL`/`S3_BUCKET`/`S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` to be set. App startup (`interface/api/app.py` lifespan) refuses to boot in distributed mode if object storage isn't configured — Redis-without-S3 is an invalid combination.

**Known issue**: none in the adapter. Until 2026-10-28 the `object_storage` capability probe swallowed `head_bucket` errors without logging them, so an `unavailable` row left no trace in the Railway logs. It now logs the traceback and the S3 error code (search the backend logs for `Object storage probe failed` or `object_storage=unavailable`). See `capabilities.md`.

**Tests**: none currently (would need a real or mocked S3-compatible endpoint; local dev's `docker-compose.yml` provides MinIO for manual testing).

## Changelog
- 2026-10-28 · claude (session ccr-ee9ca9d3) · noted where the object-storage probe failure reason now shows up in the logs
