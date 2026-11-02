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
   - Paths (a) and (b) record the length `enforce_duration_cap` returns via `RunRepository.set_duration` (`_record_duration`, which logs and swallows a write failure — the duration is cosmetic and must never fail a healthy run). The caption fallback records `CaptionTrack.duration_seconds` (yt-dlp's reported length) the same way.
3. If no usable path/dir resulted, raise `MediaValidationError("No media source was provided.")`.
4. Stage → `"normalizing"`, then `MediaProcessor.normalize_media`.
5. `AnalysisEngine.analyze_with_retry`, with an `on_stage` callback that relays Gemini's own stages (`"uploading_to_gemini"`, `"analyzing"`) into `RunRepository.set_stage`, and the `SourceMetadata` from step 2 when there was one. The metadata is both persisted onto the run *and* passed to the engine — persisting it makes it visible in the UI, passing it makes the analysis better (see `docs/backend/gemini-analysis.md`). Upload and S3 paths pass `None`.
6. `RunRepository.set_result` on success, with `AnalysisCompleteness.FULL`.

**History poster (Phase 5a)**: as soon as the source is on disk (after the duration cap on paths (a)/(b); right after step 3 on path (c)), `_start_visuals` launches `MediaProcessor.describe_visuals` as an `asyncio` task that runs **alongside** normalize/analyze, so it adds no latency. Inputs: the local file plus, for URL runs, yt-dlp's `thumbnail_urls`/`width`/`height` hints from `SavedUpload`. `_record_visuals` awaits it and writes `RunRepository.set_visuals` **immediately before** `set_result`, so the first poll that sees `complete` already carries `thumbnail`/`width`/`height`. The caption fallback does the same with `CaptionTrack`'s hints and no file. Every failure (the capture raising, the write raising) is logged and swallowed — a missing poster never fails a run. On any failure/cancellation path `finally` cancels an unfinished capture (`_discard_visuals`) **before** `cleanup_run_dir` deletes the file it may be reading. Failed runs get no visuals.

**Caption fallback (URL runs only)**: if step 2(b) raises `MediaValidationError` — every resolver in the chain failed — the pipeline tries `MediaProcessor.fetch_captions` before giving up. Platforms serve subtitles from a different pipeline than media bytes, so a 403 on the video very often coexists with a perfectly available caption track. On success the run completes with stage `analyzing_captions`, `AnalysisCompleteness.CAPTIONS_ONLY`, and a text-only analysis (`AnalysisEngine.analyze_captions`, see `docs/backend/gemini-analysis.md`); `SourceMetadata` recovered alongside the captions is persisted too. Verified end-to-end against a YouTube URL that returns `HTTP 403` on download.

Any failure inside the fallback returns False and the **original download error** is re-raised — the caption attempt is a bonus and its own problems must never replace the diagnosis of why the download failed. Upload and S3 runs never enter this path (there is no URL to fetch captions from).

**Error handling — three distinct paths**, all terminal (none re-raise out of `execute`):
- `MediaValidationError` / `GeminiConfigurationError` → stored verbatim as `run.error` (these already carry a caller-safe message).
- `asyncio.CancelledError` → marks the run failed with `RUN_INTERRUPTED_MESSAGE`, then **re-raises**. This branch exists because `CancelledError` is a `BaseException`: arq cancels the coroutine when `job_timeout` expires, and the catch-all below never sees it, so the run would sit in `PROCESSING` until its TTL expired days later. The write is best-effort (the loop may already be tearing down), which is what the read-time staleness check backstops.
- Anything else → logged with `logger.exception`, but the *stored* `run.error` is always the fixed string `"Media analysis failed. Please try again."` — deliberately masks internals (stack traces, credentials, third-party error text) from ever reaching the client via run status. Trade-off: debugging a failed run from its stored error alone tells you almost nothing; you need the server logs for the real cause.

**Free-run refund (`finally`, always runs)**: `_settle_free_run` calls `FreeRunAllowance.release(run_id, refund=rejected_before_analysis)`. `rejected_before_analysis` is set only on the link path (b), before any Gemini call: when `download_url` raised and the caption fallback did not complete the run, or when `enforce_duration_cap` raised on the downloaded file. It stays false for a caption path that failed at Gemini (the cap is never checked there), normalize, analyze, cancellation and uploads (including path (a)'s duration re-check; intake refunds over-long uploads). Release is a no-op for runs that held no free run (BYOK, allowance off) and refunds at most once. A failing release is logged and swallowed. See `free-runs.md`.

**Cleanup (`finally`, always runs)**: if `source_key` was set, deletes the S3 object — failure to delete is logged and swallowed, doesn't affect run status. Then always calls `MediaProcessor.cleanup_run_dir`.

**Abandoned runs** (the previously-documented "known issue", corrected 2026-08-29): the old note claimed a local-mode restart left a run `PROCESSING` forever. That is not what happens — in local mode `RunStore` is an in-process dict too, so a restart discards the run entirely and it returns 404. The real stranding cases were different, and both are now handled:

1. **A garbage-collected local task.** `RunQueue` dispatched local runs with a bare `asyncio.create_task(...)` and kept no reference. The event loop holds only a *weak* reference, so the task could be collected mid-run: the coroutine stops, the process lives on, and the run is stranded in `PROCESSING` in a store that is still very much alive. Fixed by holding the task in `RunQueue._local_tasks` until its done-callback discards it.
2. **A cancelled distributed job.** arq's `job_timeout` cancellation was never caught (see the error-handling list above).
3. **Backstop for everything else** — OOM kill, container replacement, any death that gives the process no chance to write. `GetRunUseCase` treats a `queued`/`processing` run whose `updated_at` is older than `worker_job_timeout_seconds + 120` as abandoned (`domain/policies.py:is_run_stale`), reports it as failed, and persists that so history agrees. This is the only mechanism that does not depend on the dying process cooperating.

`ListRunsUseCase` deliberately does **not** apply the staleness check — it would turn a history listing into a write path.

**Tests**: `backend/tests/application/test_process_run.py` — covers all three source-acquisition paths, all three error paths (including that the masked-message path really doesn't leak the original exception text), that cleanup still runs even if `delete_source` itself throws, that `SourceMetadata` reaches the analysis engine on URL runs while uploads analyze with `None`, the full caption-fallback matrix (recovery, no captions, broken fetch, failing caption analysis, uploads never trying it), and that a cancelled job is marked failed and still propagates the cancellation. Phase 5a adds: visuals written while still `PROCESSING` (before complete) on link/S3/local-upload/caption paths, the exact hints passed per path, audio writes nothing, a raising capture or write never fails the run, and a failed analysis cancels an unfinished capture before cleanup. `FreeRunDownloadRefundTests` covers the free-run refund matrix. `backend/tests/application/test_get_run.py` covers staleness; `backend/tests/infrastructure/queue/test_job_queue.py` covers the local task reference.

## Changelog
- 2026-08-29 · main session · the pipeline now forwards `SourceMetadata` to the analysis engine as well as persisting it
- 2026-08-29 · main session · added the caption fallback and `AnalysisCompleteness`; fixed the GC-able local task and the uncaught `CancelledError`, added the read-time staleness backstop, and corrected the inaccurate "known issue" note
- 2026-11-01 · backend agent (Phase 3) · URL/S3/caption paths persist the source duration via `set_duration`
- 2026-11-01 · backend agent (Phase 5a) · concurrent `describe_visuals` task per run, persisted via `set_visuals` just before `set_result`; cancelled before cleanup on failure
- 2026-11-02 · backend agent (free-run download refund) · `finally` releases the run's held free run, refunding it when the download failed
- 2026-11-02 · backend agent (duration-cap refund) · the refund now also covers a link run whose downloaded file fails the duration cap (`rejected_before_analysis`)
