# Run storage & history

Persists `Run` records and each owner's run-id history. One class, two backends selected by a single flag — no separate adapters.

**Files**
- `backend/app/infrastructure/persistence/run_repository.py` — `RunStore`, implements the `RunRepository` port.
- `backend/app/domain/entities.py` — the `Run` entity itself.

**Dual mode**, keyed off `settings.queue_enabled` (i.e. is `REDIS_URL` set):
- **Distributed**: Redis. Run JSON stored at `videolens:run:{run_id}` with TTL `RUN_TTL_SECONDS` (default 7 days). Each owner's run-id history is a Redis sorted set (`videolens:owner:{owner_id}:runs`, score = creation timestamp), capped at 50 entries (`_HISTORY_INDEX_CAP`) regardless of `RUN_TTL_SECONDS`, refreshed with the same TTL on every write.
- **Local**: an in-process `dict[str, Run]` behind an `asyncio.Lock`. No TTL, no cap — lives only as long as the process does. `list_for_owner` sorts by `created_at` descending, with insertion order as the tiebreak for same-timestamp runs (dict preserves insertion order in Python).

**API surface**: `create`, `get`, `list_for_owner(limit=20)`, `set_status`/`set_stage`/`set_result`/`set_error` (all go through one private `_update`), `ping`, `close`.

**Known behavior worth knowing**: `_update` silently no-ops if the run doesn't exist (`if run is None: return`) rather than raising — a status/stage/result update for an expired or already-cleaned-up run just does nothing, no error surfaces anywhere.

**Tests**: `backend/tests/infrastructure/persistence/test_run_repository.py` (local-mode only — constructs `RunStore(Settings())` with no `REDIS_URL`, so only the in-memory path is exercised; the Redis path has no test coverage).

**Local dev tradeoff**: bare `uvicorn app.main:app --reload` (no `REDIS_URL` in `backend/.env`) uses the in-memory path — run history is wiped on every restart. This is deliberate for fast local iteration, not a bug. For history that survives restarts during local development, run the full stack via `docker compose up -d redis minio minio-init backend worker` instead — `docker-compose.yml`'s `REDIS_URL=redis://redis:6379/0` flips `queue_enabled` on, which switches **both** run storage to Redis **and** job execution to the arq queue **and** file uploads to S3/MinIO (all three are gated by the same flag — see `create_run.py`'s `distributed` param). Don't set `REDIS_URL` for a bare `uvicorn` process without also running an arq worker and MinIO, or runs will get stuck in `"queued"` forever (nothing consumes the queue) and file uploads will fail outright (`"Object storage is not configured"`).
