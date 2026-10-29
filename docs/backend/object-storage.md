# Object storage (S3-compatible)

Temporary storage for uploaded source media in distributed mode, so the worker process (different machine/container than the API process) can retrieve it.

**Files**
- `backend/app/infrastructure/storage/s3_object_store.py` — `S3ObjectStore`, implements `ObjectStore`.

**When it's used**: only when `distributed=True` (i.e. `queue_enabled`, i.e. `REDIS_URL` set). `CreateRunUseCase` uploads under a size-cap-and-extension-validated file, in local mode the file just stays on the API process's local disk and `saved_path`/`run_dir` are passed straight to the local runner instead.

**Addressing style**: `S3_ADDRESSING_STYLE` (default `auto`) goes to botocore's `Config(s3={"addressing_style": ...})`. With a custom endpoint, `auto` means path-style (`https://endpoint/bucket`), which MinIO in docker-compose needs. On Railway, use whichever style the bucket's Credentials tab names: buckets created after Railway moved to virtual-hosted URLs take `virtual` (`https://bucket.t3.storageapi.dev`), older ones need `path`. `videolens-dev-media` (created 2026-08-13) is an older one. The wrong style comes back as a bare 403 on HeadBucket, the same code as bad keys.

**Railway credentials**: set the five `S3_*` variables as references to the bucket (`${{videolens-dev-media.BUCKET}}`, `ENDPOINT`, `REGION`, `ACCESS_KEY_ID`, `SECRET_ACCESS_KEY`), never pasted copies. `BUCKET` is the hashed S3 name, not the display name, and pasted keys go stale silently: dev's did, which is why its `object_storage` row was red from at least 2026-10-22 until 2026-10-29. `tests/infrastructure/storage/test_s3_object_store.py` checks the URL each style builds.

**Key layout**: `runs/{run_id}/source{ext}` — deleted by `ProcessRunUseCase` in its `finally` block after processing (success or failure), and by `CreateRunUseCase` if enqueueing fails after the upload already happened.

**Enabled check**: `object_storage_enabled` (a `Settings` property) requires all four of `S3_ENDPOINT_URL`/`S3_BUCKET`/`S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` to be set. App startup (`interface/api/app.py` lifespan) refuses to boot in distributed mode if object storage isn't configured — Redis-without-S3 is an invalid combination.

**Known issue**: none in the adapter. Until 2026-10-28 the `object_storage` capability probe swallowed `head_bucket` errors without logging them, so an `unavailable` row left no trace in the Railway logs. It now logs the traceback and the S3 error code (search the backend logs for `Object storage probe failed` or `object_storage=unavailable`). See `capabilities.md`.

**Tests**: `tests/infrastructure/storage/test_s3_object_store.py` (addressing style only, via presigned URLs, no network). Anything touching a real bucket still needs MinIO from `docker-compose.yml`.

## Changelog
- 2026-10-28 · claude (session ccr-ee9ca9d3) · noted where the object-storage probe failure reason now shows up in the logs
- 2026-10-28 · claude (session ccr-ee9ca9d3) · added `S3_ADDRESSING_STYLE`; dev's bucket has failed `head_bucket` since at least 2026-10-22 and Railway documents virtual-hosted URLs
- 2026-10-29 · claude (session ccr-ee9ca9d3) · corrected the addressing-style advice (older Railway buckets need `path`) and documented bucket references for the S3 credentials
