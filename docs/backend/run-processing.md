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
6. `RunRepository.set_result` on success, with `AnalysisCompleteness.FULL`.

**Caption fallback (URL runs only)**: if step 2(b) raises `MediaValidationError` — every resolver in the chain failed — the pipeline tries `MediaProcessor.fetch_captions` before giving up. Platforms serve subtitles from a different pipeline than media bytes, so a 403 on the video very often coexists with a perfectly available caption track. On success the run completes with stage `analyzing_captions`, `AnalysisCompleteness.CAPTIONS_ONLY`, and a text-only analysis (`AnalysisEngine.analyze_captions`, see `docs/backend/gemini-analysis.md`); `SourceMetadata` recovered alongside the captions is persisted too. Verified end-to-end against a YouTube URL that returns `HTTP 403` on download.

Any failure inside the fallback returns False and the **original download error** is re-raised — the caption attempt is a bonus and its own problems must never replace the diagnosis of why the download failed. Upload and S3 runs never enter this path (there is no URL to fetch captions from).

**Error handling — three distinct paths**, all terminal (none re-raise out of `execute`):
- `MediaValidationError` / `GeminiConfigurationError` → stored verbatim as `run.error` (these already carry a caller-safe message).
- `asyncio.CancelledError` → marks the run failed with `RUN_INTERRUPTED_MESSAGE`, then **re-raises**. This branch exists because `CancelledError` is a `BaseException`: arq cancels the coroutine when `job_timeout` expires, and the catch-all below never sees it, so the run would sit in `PROCESSING` until its TTL expired days later. The write is best-effort (the loop may already be tearing down), which is what the read-time staleness check backstops.
- Anything else → logged with `logger.exception`, but the *stored* `run.error` is always the fixed string `"Media analysis failed. Please try again."` — deliberately masks internals (stack traces, credentials, third-party error text) from ever reaching the client via run status. Trade-off: debugging a failed run from its stored error alone tells you almost nothing; you need the server logs for the real cause.

**Cleanup (`finally`, always runs)**: if `source_key` was set, deletes the S3 object — failure to delete is logged and swallowed, doesn't affect run status. Then always calls `MediaProcessor.cleanup_run_dir`.

**Abandoned runs** (the previously-documented "known issue", corrected 2026-08-29): the old note claimed a local-mode restart left a run `PROCESSING` forever. That is not what happens — in local mode `RunStore` is an in-process dict too, so a restart discards the run entirely and it returns 404. The real stranding cases were different, and both are now handled:

1. **A garbage-collected local task.** `RunQueue` dispatched local runs with a bare `asyncio.create_task(...)` and kept no reference. The event loop holds only a *weak* reference, so the task could be collected mid-run: the coroutine stops, the process lives on, and the run is stranded in `PROCESSING` in a store that is still very much alive. Fixed by holding the task in `RunQueue._local_tasks` until its done-callback discards it.
2. **A cancelled distributed job.** arq's `job_timeout` cancellation was never caught (see the error-handling list above).
3. **Backstop for everything else** — OOM kill, container replacement, any death that gives the process no chance to write. `GetRunUseCase` treats a `queued`/`processing` run whose `updated_at` is older than `worker_job_timeout_seconds + 120` as abandoned (`domain/policies.py:is_run_stale`), reports it as failed, and persists that so history agrees. This is the only mechanism that does not depend on the dying process cooperating.

`ListRunsUseCase` deliberately does **not** apply the staleness check — it would turn a history listing into a write path.

**Tests**: `backend/tests/application/test_process_run.py` — covers all three source-acquisition paths, all three error paths (including that the masked-message path really doesn't leak the original exception text), that cleanup still runs even if `delete_source` itself throws, that `SourceMetadata` reaches the analysis engine on URL runs while uploads analyze with `None`, the full caption-fallback matrix (recovery, no captions, broken fetch, failing caption analysis, uploads never trying it), and that a cancelled job is marked failed and still propagates the cancellation. `backend/tests/application/test_get_run.py` covers staleness; `backend/tests/infrastructure/queue/test_job_queue.py` covers the local task reference.

## Changelog
- 2026-08-29 · main session · the pipeline now forwards `SourceMetadata` to the analysis engine as well as persisting it
- 2026-08-29 · main session · added the caption fallback and `AnalysisCompleteness`; fixed the GC-able local task and the uncaught `CancelledError`, added the read-time staleness backstop, and corrected the inaccurate "known issue" note
