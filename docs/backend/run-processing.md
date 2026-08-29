# Run processing pipeline

Does the actual work for one run: get the source media onto disk, validate/normalize it, analyze it with Gemini, persist the result. Runs identically whether invoked by the local in-process runner or the arq worker — it has no idea which.

**Files**
- `backend/app/application/process_run.py` — `ProcessRunUseCase.execute()`, the whole pipeline.
- `backend/app/interface/worker/settings.py` — arq's `process_run` job function, which is a thin wrapper calling this use case.
- `backend/app/infrastructure/queue/job_queue.py` — the local (non-distributed) path calls this use case's `execute` directly as a bound callable (`local_runner`).

**Flow**
1. Status → `PROCESSING`.
2. Get the source onto disk, one of three ways: (a) `source_key` set → download from S3 via `ObjectStore.download_source`, then re-run the duration cap (the file wasn't validated in this process before); (b) `source_url` set → stage `"downloading"`, then `MediaProcessor.download_url`, then duration cap; (c) neither set → `saved_path`/`run_dir` were passed in directly (local-mode upload, already duration-capped by `CreateRunUseCase` before enqueueing — **not** re-validated here).
   - For path (b), if the download returned a `SourceMetadata` (yt-dlp's own post metadata — title, uploader, caption, upload date, like/view/comment counts; see `docs/backend/media-validation.md`), it's persisted immediately via `RunRepository.set_source_metadata` — before normalize/analyze — so it's visible on `GET /api/runs/{id}` even if a later stage fails. File-upload runs never have this (`SavedUpload.metadata` is `None` for uploads).
3. If no usable path/dir resulted, raise `MediaValidationError("No media source was provided.")`.
4. Stage → `"normalizing"`, then `MediaProcessor.normalize_media`.
5. `AnalysisEngine.analyze_with_retry`, with an `on_stage` callback that relays Gemini's own stages (`"uploading_to_gemini"`, `"analyzing"`) into `RunRepository.set_stage`, and the `SourceMetadata` from step 2 when there was one. The metadata is both persisted onto the run *and* passed to the engine — persisting it makes it visible in the UI, passing it makes the analysis better (see `docs/backend/gemini-analysis.md`). Upload and S3 paths pass `None`.
6. `RunRepository.set_result` on success.

**Error handling — three distinct paths**, all terminal (none re-raise out of `execute`):
- `MediaValidationError` / `GeminiConfigurationError` → stored verbatim as `run.error` (these already carry a caller-safe message).
- Anything else → logged with `logger.exception`, but the *stored* `run.error` is always the fixed string `"Media analysis failed. Please try again."` — deliberately masks internals (stack traces, credentials, third-party error text) from ever reaching the client via run status. Trade-off: debugging a failed run from its stored error alone tells you almost nothing; you need the server logs for the real cause.

**Cleanup (`finally`, always runs)**: if `source_key` was set, deletes the S3 object — failure to delete is logged and swallowed, doesn't affect run status. Then always calls `MediaProcessor.cleanup_run_dir`.

**Known issue**: the local (non-distributed) job queue has no persistence — an in-flight run is just an `asyncio.create_task`. A server restart mid-run drops it silently; the run stays `PROCESSING` forever with nothing to resume or fail it. Distributed mode doesn't have this problem (arq re-delivers on worker restart).

**Tests**: `backend/tests/application/test_process_run.py` — covers all three source-acquisition paths, all three error paths (including that the masked-message path really doesn't leak the original exception text), and that cleanup still runs even if `delete_source` itself throws.

## Changelog
- 2026-08-29 · main session · the pipeline now forwards `SourceMetadata` to the analysis engine as well as persisting it
