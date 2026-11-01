# Run storage & history

Persists `Run` records and each owner's run-id history. One class, two backends selected by a single flag — no separate adapters.

**Files**
- `backend/app/infrastructure/persistence/run_repository.py` — `RunStore`, implements the `RunRepository` port.
- `backend/app/domain/entities.py` — the `Run` entity itself.
- `backend/app/domain/run_facts.py` — read-time derivations for the history grid (see below).

**Dual mode**, keyed off `settings.queue_enabled` (i.e. is `REDIS_URL` set):
- **Distributed**: Redis. Run JSON stored at `videolens:run:{run_id}` with TTL `RUN_TTL_SECONDS` (default 7 days). Each owner's run-id history is a Redis sorted set (`videolens:owner:{owner_id}:runs`, score = creation timestamp), capped at 50 entries (`_HISTORY_INDEX_CAP`) regardless of `RUN_TTL_SECONDS`, refreshed with the same TTL on every write.
- **Local**: an in-process `dict[str, Run]` behind an `asyncio.Lock`. No TTL, no cap — lives only as long as the process does. `list_for_owner` sorts by `created_at` descending, with insertion order as the tiebreak for same-timestamp runs (dict preserves insertion order in Python).

**API surface**: `create(run_id, owner_id, *, source_kind=None, platform=None, duration_seconds=None)`, `get`, `list_for_owner(limit=20)`, `set_status`/`set_stage`/`set_result`/`set_source_metadata`/`set_duration`/`set_error` (all go through one private `_update`), `ping`, `close`.

**Media facts on `Run`** (added 2026-11-01 for the Phase 3 history poster grid). Three optional fields, all defaulting to `None` so a run JSON written by an older release (no such keys) still deserializes and lists with `None`s — no migration:
- `source_kind` — `"link"` / `"file"`, set by `CreateRunUseCase` at create time.
- `platform` — stored **only for file runs**: `"audio_file"` for `.mp3`, else `"video_file"`, from the extension of the saved path (`upload<ext>`). The submitted filename is never stored (it can carry personal info). Link runs store nothing here; their platform is derived at read time from `source_metadata`.
- `duration_seconds` — ffprobe's length from `enforce_duration_cap` (uploads at create time; URL/S3 sources via `set_duration` in `ProcessRunUseCase`), or yt-dlp's `duration` on the caption-fallback path. Stays `None` if never probed (e.g. download failed with no captions).

Nothing about the user is stored — only facts about the media.

**Read-time derivation** (`domain/run_facts.py:describe_run`, used by both `GET /api/runs` and `GET /api/runs/{id}`):
- `source_kind`: stored value; for a legacy run, `"link"` if `source_metadata` exists, else `None`.
- `platform`: one of `youtube | instagram | tiktok | audio_file | video_file | other`. Links: yt-dlp `extractor_key` by prefix (`Youtube`, `YoutubeTab` → youtube; `Instagram*`; `TikTok*`), then `source_url` host, else `other`. A link run with no `source_metadata` → `None` (the URL itself isn't stored).
- `orientation` (list only): `landscape` for YouTube URLs not under `/shorts/`; `portrait` for Shorts and every other known platform (incl. file runs); `None` when platform unknown.
- `summary_snippet` (list only, never stored): `result.summary` whitespace-collapsed, cut at a word boundary to ≤160 chars including a trailing `…`.

**Known behavior worth knowing**: `_update` silently no-ops if the run doesn't exist (`if run is None: return`) rather than raising — a status/stage/result update for an expired or already-cleaned-up run just does nothing, no error surfaces anywhere.

**Tests**: `backend/tests/domain/test_run_facts.py` (derivations), `backend/tests/interface/api/test_run_routes.py` (list/status response shape incl. a legacy run), `backend/tests/infrastructure/persistence/test_run_repository.py` (local-mode only — constructs `RunStore(Settings())` with no `REDIS_URL`, so only the in-memory path is exercised; the Redis path has no test coverage).

**Local dev tradeoff**: bare `uvicorn app.main:app --reload` (no `REDIS_URL` in `backend/.env`) uses the in-memory path — run history is wiped on every restart. This is deliberate for fast local iteration, not a bug. For history that survives restarts during local development, run the full stack via `docker compose up -d redis minio minio-init backend worker` instead — `docker-compose.yml`'s `REDIS_URL=redis://redis:6379/0` flips `queue_enabled` on, which switches **both** run storage to Redis **and** job execution to the arq queue **and** file uploads to S3/MinIO (all three are gated by the same flag — see `create_run.py`'s `distributed` param). Don't set `REDIS_URL` for a bare `uvicorn` process without also running an arq worker and MinIO, or runs will get stuck in `"queued"` forever (nothing consumes the queue) and file uploads will fail outright (`"Object storage is not configured"`).

## Changelog
- 2026-11-01 · backend agent (Phase 3) · added `source_kind`/`platform`/`duration_seconds` to `Run`, `set_duration` on the repository, and `domain/run_facts.py` read-time derivations for the history poster grid (`RunSummary` gains `source_kind`, `platform`, `duration_seconds`, `summary_snippet`, `orientation`)
