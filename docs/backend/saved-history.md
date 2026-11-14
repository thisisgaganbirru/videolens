# Saved history (paid) and the account deletion hold

Owner decisions of 2026-11-14 reverse "no server-side persistence for runs
or results" for one case: **a paid account's results are saved on the
server**. Free and anonymous use is unchanged, and so is the browser's own
History (IndexedDB), which every caller still gets. The same decisions make
`DELETE /api/me` a 30-day hold instead of an immediate removal, for every
account, free ones too.

Both are off (nothing saved, nothing held, every list empty) without a
database. Saving also needs billing on: with any required `STRIPE_*` blank
nothing is saved or removed, though rows already there stay listable and
deletable.

## Files

| File | Role |
|---|---|
| `migrations/versions/0006_saved_history.py` | `saved_runs`; `accounts.deleted_at`, `purge_at`, `saved_runs_expire_at`; RLS, grants and policy on Postgres |
| `infrastructure/persistence/schema.py` | The same tables for SQLAlchemy Core (`JSON_DOCUMENT` = JSON, JSONB on Postgres) |
| `infrastructure/persistence/saved_run_repository.py` | `SqlSavedRuns`, `InMemorySavedRuns` (the `SavedRunRepository` port) |
| `infrastructure/persistence/account_deleter.py` | The hold: `schedule_deletion`, `restore`, `due_for_purge`, `delete_account(due_before=)` |
| `application/saved_history.py` | `SavedHistory` (saving, the window rules) and `SavedHistoryQueries` (the API side); cursor encoding |
| `application/delete_account.py` | `DELETE /api/me`: cancel the subscription, drop the Redis runs, start the hold |
| `application/restore_account.py` | `POST /api/me/restore` |
| `application/cleanup.py` | The worker's hourly cleanup (`AccountCleanupUseCase`) |
| `application/process_run.py` | Calls `SavedHistory.save_completed` after the result is stored and the extra run billed |
| `application/handle_billing_webhook.py` | Calls `SavedHistory.sync_expiry` after each subscription change |
| `application/identify_caller.py` | Refuses a held account (410), and its API keys (401) |
| `interface/api/routes.py`, `schemas.py`, `dependencies.py`, `error_handlers.py` | The endpoints below; `require_person_even_if_deleted` for the restore only |
| `interface/worker/settings.py` | `account_cleanup` cron, minute 25 of every hour |

## API contract

All of these need a signed-in session (`require_person`): anonymous is 401,
an API key is 403 (owner decision 2026-11-14: API keys cannot read saved
history). They always act on the caller's own account; another
account's run id is a plain 404. Rate limit: the read limit.

### `GET /api/history?limit=20&cursor=`

`limit` 1..100 (422 outside), `cursor` opaque, at most 200 characters (400
`That page of your history could not be found. Reload and try again.` when
it does not decode).

```json
{
  "saving": true,
  "expires_at": null,
  "items": [
    {
      "run_id": "…",
      "title": "…",
      "summary_snippet": "≤ 160 characters, or null",
      "completeness": "full",
      "created_at": "2026-11-14T12:00:00Z",
      "thumbnail": "data:image/jpeg;base64,/9j/… (≤ 20 KB), or null",
      "source": {
        "source_kind": "link",
        "platform": "youtube",
        "source_url": "https://…",
        "source_title": "…",
        "uploader": "…",
        "duration_seconds": 42.0,
        "width": 1080,
        "height": 1920
      }
    }
  ],
  "next_cursor": "opaque, or null on the last page"
}
```

Newest first (`created_at` = when the run was created, then the row id).
Light fields only: no transcript, no notes.

`thumbnail` is the run's poster, under the same name and in the same shape
as a finished run's `GET /api/runs/{run_id}` `thumbnail`: a ≤ 20 KB
`data:image/jpeg;base64,...` URL, or `null` when the run had none (audio,
capture failed, or the size guard dropped it). It is a top-level field of
the item, not part of `source`, and is always present. The frontend can
render a saved card with the code it uses for its own History. A 20-item
page of posters is at most ~400 KB.

A source field is null when it
is not known; a file run has no `source_url` (the server never keeps a file
name).

- **Free account that never paid:** `{"saving": false, "expires_at": null, "items": [], "next_cursor": null}`.
- **Post-cancel window:** `saving: false`, `expires_at` set, the saved runs
  listed as before.
- **Paid:** `saving: true`, `expires_at: null`.

### `GET /api/history/{run_id}`

The summary fields above (including `thumbnail`) plus `result`, the full
saved `VideoAnalysis` (title, summary, transcript, screen_text, markdown,
transcript_segments, screen_text_segments). 404 `That saved run was not found.`

### `DELETE /api/history/{run_id}`

204, no body. 404 when the account has no such saved run (including a
second delete).

### `DELETE /api/history`

`{"deleted": <n>}`: every saved run of the account. Works in the window
too.

### `GET /api/me`

Gains `"saved_history": {"saving": bool, "expires_at": datetime | null}`,
the same two fields as the list.

### `DELETE /api/me` (changed)

**200 now, was 204**: `{"status": "pending_deletion", "purge_at": "…Z"}`.
The frontend checks `res.ok`, so it keeps working. Errors as before
(401/403/503 `subscription_cancel_failed`/500). A second call during the
hold is the 410 below.

### `POST /api/me/restore` (new)

The one endpoint a held account may call. A signed-in session only
(anonymous 401, API key 403).

- `{"restored": true}`: the hold is lifted. Same account id, workspace, API
  keys and saved runs; on the free plan (the subscription was cancelled at
  deletion; resubscribing is a fresh checkout).
- `{"restored": false}`: the account was not held; nothing changes.
- 410 `{"detail": "…", "code": "restore_window_closed"}`: `purge_at` has
  passed. The cleanup removes it (or already has).

### Held account, every other endpoint

A bearer token for an account in the hold is refused wherever identity is
resolved (`/api/me`, `/api/keys`, `/api/history`, `/api/billing`,
`POST /api/runs` with the token, `DELETE /api/me` again):

```json
410 {"detail": "This account was deleted. You can restore it until it is removed for good.",
     "code": "account_pending_deletion", "purge_at": "2026-12-14T12:00:00Z"}
```

Its API keys are `401 Invalid API key.`: **blocked, not revoked** (owner
decision 2026-11-14), so they come back on restore. The same sign-in cannot
start a fresh account during the hold (owner decision 2026-11-14): it gets
this 410 until it restores or the hold ends. Signed out, the person can keep
using the app anonymously.

## Rules

### What is saved, and when

`ProcessRunUseCase` calls `SavedHistory.save_completed(run_id, source_url)`
right after `set_result` succeeds and the extra run is billed, on both the
caption path and the main path. It saves only when:

- the run is `COMPLETE` with a result, and
- the run has an `account_id` (recorded at intake on the Redis run record,
  never a job argument), and
- that account is on the paid plan **at completion time**
  (`BillingPlans.paid_account`: active or trialing within its period plus 3
  days). A run started while paid that finishes after the plan ended is not
  saved; one started free that finishes paid is.

Runs made with the account's API keys are saved too (same account). BYOK
runs are saved like any other (the key is never part of the record).

Saved: title, summary snippet, the full `VideoAnalysis` as JSON,
`completeness`, `created_at`, a source descriptor (kind, platform, the
public link for a link run, the publisher's title and uploader, duration,
width, height), and the poster thumbnail (`Run.thumbnail` as is, the ≤ 20 KB
JPEG data URL the live run exposes; owner decision 2026-11-14). **Never**
saved: any other media, any key, the file name.

**Idempotent**: `(account_id, run_id)` is unique and the insert is `ON
CONFLICT DO NOTHING`, so a retried job saves once.

**Never fails the run**: any error is logged (`Could not save run … to its
account's history`) and swallowed. The run stays complete and billed.

### Size guard: `PAID_SAVED_RUN_MAX_BYTES` = 2 MiB

Measured as compact UTF-8 JSON of the result plus the poster data URL's
length. Over it, in this order:

1. drop the two segment lists (they only time text that is kept in full);
2. still over: drop the poster too (`thumbnail` saved as null);
3. still over: the run is not saved, ERROR logged.

Steps 1 and 2 log a WARNING naming what was dropped. The text (title,
summary, transcript, on-screen text, notes) is never trimmed. 2 MiB is far
above a real result (a 10-minute run's transcript is tens of KB) and well
under Postgres' limits; it exists so one pathological result cannot bloat
the table.

### The post-cancel window: `PAID_SAVED_RUNS_GRACE_DAYS` = 30

- It starts when the plan has **ended**: `policies.subscription_has_ended`
  (not paid, and not `past_due`/`incomplete`, which Stripe may still
  settle). `canceled`, `unpaid`, `incomplete_expired`, and an `active` row
  whose period ended more than 3 days ago all count.
- The webhook arms it (`sync_expiry`, once; a repeat event keeps the first
  date). The cleanup's backstop (`arm_lapsed`) arms any the webhook missed.
- During it: nothing new is saved; the runs are readable and deletable.
- **Resubscribe** inside it: the webhook clears `saved_runs_expire_at`;
  everything stays. The purge also re-checks the plan, so a resubscribe
  whose webhook has not arrived yet is cleared, not purged.
- After it: the cleanup removes the account's saved runs for good and
  clears the date.

### The deletion hold: `ACCOUNT_DELETION_HOLD_DAYS` = 30

`DELETE /api/me`, in order:

1. Cancel any Stripe subscription now (unchanged, `invoice_now=true,
   prorate=false`, after reporting due extra runs). A failure refuses the
   deletion (503) with nothing changed.
2. Delete the person's Redis runs (unchanged, best effort).
3. Set `accounts.deleted_at = now`, `purge_at = now + hold` (only if not
   already set). From here the account is refused everywhere (above).

Rows stay: account, workspace, members, API keys, billing link, free-run
counters, saved runs. **The Supabase user stays too**: the person has to be
able to sign in to restore. Saved runs of a held account are never touched
by the window scans. A restore re-arms a fresh full window for them (from
the restore, since the account is now free), so the hold never eats into
it.

After `purge_at`, the hourly cleanup, per account (25 per tick):

1. If a subscription is somehow live again, cancel it; if that fails, skip
   the account (logged) and retry next tick. Never remove an account that
   pays.
2. Delete the Supabase user (`videolens_private.delete_auth_user`, migration
   0002; no SDK, no service-role key). First, so nobody can sign in to a
   half-removed account.
3. Delete every row in one transaction, re-checked `purge_at <= now` under a
   row lock (`FOR UPDATE` on Postgres): a restore that raced in wins.

A failure at 2 or 3 leaves the account row; the next tick retries. Both are
idempotent. Afterwards the old token is 401 (the first-sight check finds no
Supabase user), and a fresh sign-up gets a new account.

### Cleanup job

`account_cleanup` (worker cron, minute 25 hourly, not at startup):
held accounts past `purge_at` first, then `arm_lapsed` (up to 200
accounts), then `purge_expired` (up to 25 accounts). Each step logs and
returns on error; nothing is retried in-tick. Safe on any number of
workers: every removal is a conditional write. There is no cron in local
in-process mode (no worker): holds and windows simply never end there.

## Storage

`saved_runs`:

| Column | Type | Notes |
|---|---|---|
| `id` | varchar(36) PK | uuid4, the keyset tiebreaker |
| `account_id` | varchar(36) FK `accounts.id` `ON DELETE CASCADE` | |
| `run_id` | varchar(36) | unique with `account_id` (`uq_saved_runs_account_run`) |
| `title` | varchar(500) | |
| `summary_snippet` | varchar(400) null | |
| `completeness` | varchar(16) | the run's `AnalysisCompleteness` value |
| `source` | JSONB | descriptor, nulls dropped |
| `result` | JSONB | the `VideoAnalysis` |
| `result_bytes` | integer | size of `result` as saved, for operators (the poster not included) |
| `thumbnail` | text null | the poster data URL, as `Run.thumbnail`; null when none or dropped by the size guard |
| `created_at` | timestamptz | the run's creation time |

Index `ix_saved_runs_account_created (account_id, created_at, id)` serves the
list. `accounts` gains `deleted_at`, `purge_at`, `saved_runs_expire_at`
(timestamptz null, no default: a catalog-only change on Postgres) and
indexes on the last two (the cleanup's scans).

RLS on `saved_runs` with `GRANT SELECT, INSERT, UPDATE, DELETE` and the
`videolens_api_all` policy, as 0001/0003/0004. The migration refuses to run
on Postgres if `DATABASE_APP_ROLE` does not exist.

## Settings

| Variable | Default | Where |
|---|---|---|
| `PAID_SAVED_RUNS_GRACE_DAYS` | 30 | backend and worker |
| `PAID_SAVED_RUN_MAX_BYTES` | 2097152 | worker (read on both) |
| `ACCOUNT_DELETION_HOLD_DAYS` | 30 | backend |

## Deploy order

1. Apply `0006_saved_history` (offline: `alembic upgrade
   0005_account_daily_free_runs:0006_saved_history --sql`). Before the code:
   the code reads the new `accounts` columns on every signed-in request.
2. Deploy backend and worker together (the worker saves and runs the cron).

## Tests

- `tests/application/test_saved_history.py`: saving (paid once, free/
  anonymous/billing off never, file runs keep no link, failure swallowed,
  size guard), the pipeline seam, queries and isolation between accounts,
  paging and cursors, the window (cancel, expiry, repeat webhook,
  resubscribe, purge re-check, past_due, backstop), the hold with restore
  and cleanup.
- `tests/application/test_delete_account.py`: the hold order and failures.
- `tests/infrastructure/persistence/test_saved_run_repository.py`: SQL and
  in-memory behaviour suite, the SQL hold, `accounts_to_arm` filters,
  migration 0006 on SQLite (up and down), offline Postgres SQL, the mocked
  Postgres branch.
- `tests/interface/api/test_history_routes.py`,
  `tests/interface/api/test_account_routes.py`: the HTTP contract, 410s,
  restore, the cleanup end to end.

## Known issues and open questions

- **Not run against Postgres.** SQL adapters are exercised on SQLite; the
  Postgres branch of 0006 with mocks and an offline render. The JSONB
  columns, `ON CONFLICT`, and `FOR UPDATE` have not run on a real database.
- Confirmed by the owner 2026-11-14, no longer open: during the hold the
  same sign-in cannot start a fresh account; API keys are blocked, not
  revoked, and return on restore; API keys cannot read `/api/history` (403).
- The frontend has no UI for any of this yet (backend only).
- Local in-process mode has no cron, so holds and windows never end there.

## Changelog

- 2026-11-14 · backend agent · saved runs keep the poster: `saved_runs.thumbnail` (text null, in 0006 in place), `thumbnail` on every `GET /api/history` item and on `GET /api/history/{run_id}`, same shape as a live run's; size guard drops segments, then the poster, then skips; recorded the owner's confirmations on keys during the hold, no fresh account during the hold, no API-key history reads
- 2026-11-14 · backend agent · created: paid saved history (migration 0006, saving on success, `/api/history*`, `saved_history` on `/api/me`), the post-cancel window, the 30-day deletion hold with `POST /api/me/restore`, and the hourly cleanup cron
