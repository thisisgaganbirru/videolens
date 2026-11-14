# Saved history and the account deletion hold (frontend)

The client half of two owner decisions from 2026-11-14. The backend half,
with the full contract, is `docs/backend/saved-history.md`.

- **Paid accounts save every successful run** to the account: unlimited,
  synced, the result text and the poster thumbnail, never the media.
  Free and anonymous users keep exactly what they had: the last 20 runs in
  this browser, not synced (`run-history.md`).
- **After a paid plan ends**, saved runs stay readable and deletable until
  `expires_at` (30 days), with no new saves. Resubscribing keeps them.
- **Deleting an account holds it for 30 days.** It stops working at once.
  Signing in again with the same email during the hold offers "Restore
  account", which brings the account and its saved runs back on the free
  plan. During the hold the same email cannot start a new account. After
  30 days everything is purged and the same sign-in starts a new account.

With sign-in off, billing off, or a backend without the routes, nothing on
screen changes.

## Contract used

| Call | Used for |
|---|---|
| `GET /api/me` → `saved_history: {saving, expires_at}` | typed on `AccountResponse`; the History page reads the same two fields from the list instead |
| `GET /api/history?limit=20&cursor=` | `{saving, expires_at, items[], next_cursor}`, newest first |
| `GET /api/history/{run_id}` | the summary plus `result` |
| `DELETE /api/history/{run_id}` | 204; a 404 counts as already gone |
| `DELETE /api/history` | `{deleted: n}` |
| `DELETE /api/me` | **200** `{status: "pending_deletion", purge_at}` (was 204) |
| `POST /api/me/restore` | `{restored: true|false}`; 410 `restore_window_closed` |
| any route, held account | 410 `{code: "account_pending_deletion", purge_at}` |

Each history item carries `thumbnail` at the top level: a
`data:image/jpeg;base64,...` string (at most about 20 KB) or `null`, the
same value as a finished run's `thumbnail`. The gateway keeps it only when it
starts with `data:image/`; the CSP already allows `img-src data:`.

## Layers

| Layer | File | Role |
|---|---|---|
| domain | `domain/entities.ts` | `SavedHistoryStatus`, `SavedRunSource`, `SavedRunSummary`, `SavedRunPage`, `SavedRunDetail`, `AccountDeletionOutcome`; `AccountResponse.saved_history` |
| domain | `domain/errors.ts` | `ApiError.purgeAt` |
| domain | `domain/ports.ts` | `SavedHistoryGateway`; `AccountGateway.deleteAccount()` returns the outcome, `restoreAccount()`; `AccountHoldSource` |
| infrastructure | `infrastructure/savedHistoryGateway.ts` | `FetchSavedHistoryGateway`, tolerant parsing (unknown fields dropped, a missing `items` array is an error) |
| infrastructure | `infrastructure/apiClient.ts` | every response passes `noticeHold`: a 410 `account_pending_deletion` is told to `AccountHoldSource` listeners with the identity it went out as |
| infrastructure | `infrastructure/accountGateway.ts` | 200 or legacy 204 on delete; restore |
| application | `application/useSavedHistory.ts` | one module store (like `useBilling`): first page, load more, forget, delete one, delete all; `mode` |
| application | `application/accountHold.ts` | holds heard per `user:<id>`; `useAccountHold`, `useAccountRestore`, `useRestoredEpoch` |
| application | `application/useAccount.ts` | `held` problem kind; deletion hands on `purgeAt`; re-reads after a restore |
| application | `application/useAnalysisRun.ts` | `openSavedRun(summary)` and `expiredReason` |
| components | `panels/HistoryPanel.tsx`, `ConfirmDialog.tsx`, `RunStatusView.tsx`, `HomeScreen.tsx`, `panels/AccountPanel.tsx` | the screens below |

## How History decides what to show (`SavedHistoryMode`)

`useSavedHistory(userId, enabled, paidHint)` is called once, in HomeScreen.
It asks for the first page as soon as someone is signed in where sign-in
works, again when the History tab opens, after a run of this session
finishes while saving, and after a restore.

| Mode | When | History shows |
|---|---|---|
| `off` | nobody signed in; sign-in off; 404/401/403/405 (older backend); a failed read with no sign of a paid plan; `saving: false` and no `expires_at` | today's browser-only page, unchanged |
| `pending` | signed in, first read not back | a paid account (plan or run count says paid): one row of blank posters the size of real ones; anyone else: today's page until the answer says otherwise |
| `saving` | `saving: true` | the account's runs |
| `window` | `saving: false`, `expires_at` set | the account's runs and the plan-ended notice |
| `failed` | first read failed and the account looks paid | the failure line with Try again, then everything local under "Only in this browser" |
| `held` | a 410 hold | today's page plus a calm notice linking to Account |

### The saved page

- Lede: "Every run is saved to your account, so it is here on any device
  where you sign in." (`window`: "Runs saved to your account, on any device
  where you sign in.")
- Plan ended: a quiet surface card, "Your plan has ended, so new runs are no
  longer saved. These are kept until <date>, then deleted. Resubscribe before
  then and they stay." and a "Go to Account" link.
- The account's runs in the existing poster grid and day groups, newest
  first. "Load more runs" (secondary pill) appends the next page by
  `next_cursor`; no infinite scroll. A failed page keeps the list and turns
  the control into "Try again" with a line under it.
- **No filters, search or sort** on this page (product call): over a partly
  loaded list they would answer for some runs and silently not for the rest.
- "Only in this browser": local runs whose id is not among the loaded server
  runs and, while more pages remain, no older than the oldest loaded one (so
  a run on a later page is not mislabelled). After a top rule, a muted label
  and one line ("Not saved to your account: runs from before your plan, and
  runs that did not finish. Not synced."). They open exactly as before.
- Empty (`saving`): "No saved runs yet." with the one filled "Analyze a
  video". Empty (`window`): no action.

### Opening a saved run

`openSavedRun(summary)` in `useAnalysisRun`:

1. If this browser has a finished copy (IndexedDB), it opens that with no
   network, as History always did.
2. Otherwise `GET /api/history/{id}` runs **before** anything on screen
   changes. While it does, the poster's date line says "Opening…" and the
   button is `aria-busy`.
3. Success: the result is set (`status: complete`, completeness, source card
   from `source`), HomeScreen pushes to Analyze with "Back to History".
4. 404: the run is marked gone (`markSavedRunGone`) and the expired view
   shows with
   `expiredReason: "saved"`: pill "Unavailable", title "This run is no
   longer saved", "It may have been deleted on another device." plus the
   usual "Analyze it again" (with the link when there is one) and "Back to
   History". The card is not pulled from the grid while it is still on
   screen (that shifted the page as it left); History drops it the next time
   it mounts (`goneSavedRuns()` read once at mount), and the next read from
   the server no longer has it.
5. Anything else: nothing changes on screen; History shows the reason in a
   reserved alert slot above the grid.

### Deleting

- Per run: a 2rem surface disc with a trash glyph in the thumb's empty
  top-right corner, inside a 44px target, a sibling of the card button (so
  it is its own tab stop), labelled "Delete <title> from your account".
  The platform chip's max width shrinks on those cards so they never meet.
- "Delete all saved runs": a muted underlined text control at the end of the
  list, opposite Load more.
- Both open `ConfirmDialog`: a native modal `<dialog>` on the update prompt's
  card, focus on Cancel, one solid-danger confirm, "This cannot be undone."
  It cannot be dismissed while the delete is on the wire; a failure shows
  inside it and the confirm can be pressed again.
- Deleting from the account does **not** remove this browser's own IndexedDB
  copy; the dialog says "A copy this browser keeps on its own stays here",
  and such a run then appears under "Only in this browser" (product call).

## Elsewhere

- **Result line** (`.result-saved`): "Saved to your account. Open it from
  History on any device where you sign in." for a run just finished while
  saving, or opened from the account's runs. Anything else keeps "History
  keeps your last 20 runs in this browser. Not synced."
- **Analyze retention line**: while saving, "…The result is saved to your
  account until you delete it." instead of "kept for up to an hour".
- **Account, On this device**: the row reads "History · Saved to your
  account · On every device" (or "until <date>" after the plan ended); the
  note becomes "Your Gemini key is not synced. It stays in this browser when
  you sign out."
- **Account, Upgrade comparison**: a History row, "Last 20 in this browser"
  against "Saved to your account, on every device".
- **Landing**: "Your files" and "Your history" each gain the paid-plan clause.
- **Privacy / Terms**: see `legal-offline-routes.md`.

## Account deletion and the hold

- The delete form explains the hold: stops now, kept 30 days, removed after;
  the list names saved runs and the subscription ("cancelled now"); the note
  says how to restore and that the email cannot start a new account meanwhile.
- `useAccountDeletion` hands `purgeAt` to the panel. A 410
  `account_pending_deletion` on a retry (the 200 was lost) also counts as
  done. The deleted card then says: "Sign in again with the same email
  before <date> to restore it. After that it is removed for good." A legacy
  204 keeps the old card.
- **Held** (signed in, any read answered 410 `account_pending_deletion`): the
  Account page shows one card, "This account is scheduled for deletion",
  with the email, the date, "It comes back on the free plan, with its saved
  runs.", a primary "Restore account" and a secondary "Sign out", then On
  this device and Information. Nothing else that would fail is drawn.
- Restore success: the hold is cleared, `restoredEpoch` bumps (useAccount
  and saved history re-read), billing and free runs are re-read, and a plan
  notice says "Your account is back, on the free plan. Your saved runs are
  intact."
- `restore_window_closed`: "This account can no longer be restored", with
  Sign out as the one action.
- Signing out leaves the app fully usable anonymously; the hold is keyed by
  `user:<id>`, so the anonymous identity never inherits it.

## Known limits

- The list is re-read on tab entry, not pushed: a run deleted on another
  device stays until then (and opening it gives the honest 404 view).
- Search over saved runs needs a server query; not built.
- The Terms acceptance key and the effective dates were not bumped for the
  draft text (owner's call, as in earlier draft edits).

## Changelog

- 2026-11-14 · frontend agent · created: saved-history client (gateway, store, hold source, restore), History saved page with Load more / browser-only group / plan-ended and held notices / per-run and delete-all confirmations, opening a saved run and its 404 view, result and retention lines, Account History row / Upgrade History row / delete copy / deleted card date / held and restored states, landing and legal copy
