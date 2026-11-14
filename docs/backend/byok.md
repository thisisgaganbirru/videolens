# Bring-your-own-key (BYOK)

Lets a caller supply their own Gemini API key (via `X-Gemini-Api-Key` header) so a run spends their quota instead of the shared server key's.

**Files**
- `backend/app/infrastructure/byok/key_vault.py` — `ByokKeyStore`, implements `KeyVault`.
- `backend/app/infrastructure/queue/job_queue.py` — `RunQueue.enqueue` is what actually calls `key_vault.store(...)` in distributed mode.
- `backend/app/interface/worker/settings.py` — `process_run` job function calls `key_vault.take(...)` before invoking `ProcessRunUseCase`.

**Why it exists as a separate mechanism**: in distributed mode, the API process (which receives the key from the request header) and the worker process (which actually calls Gemini with it) are different processes connected only through an arq job. arq logs job arguments and results — so the raw key can't travel as a normal job kwarg without leaking into those logs. Instead it's written to a dedicated, single-use Redis entry (`videolens:byok:{run_id}`) with a 15-minute TTL (`_KEY_TTL_SECONDS = 900`) as a safety net in case the worker crashes before reading it.

**Read-and-delete**: `take(run_id)` fetches and immediately deletes the entry — used at most once. In local (non-distributed) mode, the same interface is backed by a plain in-process dict (`self._memory`), since there's no cross-process boundary to protect against there.

**Guarantee stated in code and worth preserving**: the BYOK key is never written to `RunRepository` (the run record itself) and never logged.

**Bigger limits for signed-in BYOK (2026-11-13)**: a caller who is signed in and sends a key gets 10 minutes / 500 MB instead of 3 minutes / 200 MB (`media-validation.md`, "Limits per caller"). Anonymous BYOK is unchanged. The run's limits travel to the worker as the `limits` job kwarg (primitives only: tier and numbers, never the key); the key still goes only through this vault. Those runs use their own arq function, `process_long_run`, with a longer timeout (`job-queue.md`).

**A BYOK run never falls back to the shared key (2026-11-13)**: every run admitted on the caller's own key skipped the free-run and daily-cap checks at intake, so it must never be spent on the shared `GEMINI_API_KEY`. `CreateRunUseCase` records `Run.admitted_byok = True` on the run record (a boolean, never the key; not in any API response). When the worker has no key for the run (`ProcessRunUseCase._refuse_without_own_key`, before anything is downloaded) and the record says `admitted_byok` (or its limits are the signed-in BYOK tier), the run fails instead of running:
- still `queued` (the 15-minute vault entry expired while the job waited): "This run waited too long to start. Please try again."
- `processing` (an arq retry after the worker died: the first attempt's `take()` already deleted the key; `max_tries = 2`): "Analysis was interrupted before it finished. Please try again."
- already `complete` or `failed` (a retry of a finished job, or a queued run the read-time staleness check already failed): left as it is. Since 2026-11-13 this check runs for every job, with or without a key, and stops it before any work (`run-processing.md`, "Runs that ended elsewhere").

Both messages come from `OwnKeyUnavailableError` (`domain/errors.py`), whose `log_detail` (logged, never stored) names the cause. The refusal releases the long-run slot, deletes the S3 source and the run directory, and returns before the pipeline's `finally`, so nothing is released twice. An own-key run holds no free run and took no daily-cap unit, so there is nothing to hand back. A run whose record is gone (TTL, account deleted) is not started either, since nothing could show its result and nothing proves it was not an own-key run. Non-BYOK runs are unchanged. Runs stored before the flag existed read as `False` (the old behaviour) for the few minutes they stay queued after a deploy.

Other paths checked: the Gemini fallback model and the file-processing re-upload reuse the run's own client (`_get_client(api_key)`); the caption fallback gets the same key; the staleness check never re-enqueues. None of them can switch to the shared key.

**Local mode**: `RunQueue` hands the key straight to the in-process runner; the vault's in-process dict is not used on that path, so a local run cannot lose its key in a queue. The same `ProcessRunUseCase` check applies if it ever did.

**Tests**: none for the Redis path of the vault itself (would need a Redis instance). `tests/application/test_byok_expired_key.py` covers anonymous, signed-in standard-limit and bigger-tier BYOK with an expired key (failed with the message, Gemini and the shared key never called, nothing counted or refunded), the retry cases, a missing record, non-BYOK unchanged, the caption fallback on the run's key, and local mode end to end plus the in-process vault being single-use. `tests/application/test_media_limits.py` (`WorkerLimitsTests`) covers the bigger-tier refusal; `tests/infrastructure/queue/test_job_queue_limits.py` checks the key is never a job argument.

## Changelog
- 2026-11-13 · backend agent · signed-in BYOK gets the bigger media limits; the limits (not the key) ride on the job; a signed-in BYOK run whose vault entry expired fails instead of using the shared key; the remaining fallback recorded as a known issue
- 2026-11-13 · backend agent · known issue resolved: intake records `admitted_byok` on the run; the worker fails any own-key run with no key in the vault (expired, or taken by an earlier arq attempt) instead of using the shared key; local mode checked
- 2026-11-13 · backend agent · the ended-run check now runs for every job (keyed or not), merged with this refusal in `_drop_before_start`
