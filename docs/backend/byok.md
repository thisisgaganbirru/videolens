# Bring-your-own-key (BYOK)

Lets a caller supply their own Gemini API key (via `X-Gemini-Api-Key` header) so a run spends their quota instead of the shared server key's.

**Files**
- `backend/app/infrastructure/byok/key_vault.py` — `ByokKeyStore`, implements `KeyVault`.
- `backend/app/infrastructure/queue/job_queue.py` — `RunQueue.enqueue` is what actually calls `key_vault.store(...)` in distributed mode.
- `backend/app/interface/worker/settings.py` — `process_run` job function calls `key_vault.take(...)` before invoking `ProcessRunUseCase`.

**Why it exists as a separate mechanism**: in distributed mode, the API process (which receives the key from the request header) and the worker process (which actually calls Gemini with it) are different processes connected only through an arq job. arq logs job arguments and results — so the raw key can't travel as a normal job kwarg without leaking into those logs. Instead it's written to a dedicated, single-use Redis entry (`videolens:byok:{run_id}`) with a 15-minute TTL (`_KEY_TTL_SECONDS = 900`) as a safety net in case the worker crashes before reading it.

**Read-and-delete**: `take(run_id)` fetches and immediately deletes the entry — used at most once. In local (non-distributed) mode, the same interface is backed by a plain in-process dict (`self._memory`), since there's no cross-process boundary to protect against there.

**Guarantee stated in code and worth preserving**: the BYOK key is never written to `RunRepository` (the run record itself) and never logged.

**Known issue**: none identified — this is a carefully-scoped, single-purpose adapter.

**Tests**: none currently (would need a Redis instance or heavier mocking to test the distributed path meaningfully).
