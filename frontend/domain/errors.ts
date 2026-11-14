/* The two ways a gateway call can fail. They are separate classes because the
   honest sentence for each is different, and because only the adapter that
   calls `fetch` can tell them apart — hooks and components must never sniff
   `err instanceof TypeError` or match on message text to work it out. */

/** The server answered and the answer was a problem. `message` carries the
 *  backend's own `detail` where it sent one, so it is already specific and
 *  should be shown as-is rather than replaced with a generic line. */
export class ApiError extends Error {
  /** The backend's machine-readable `code`, when the body carried one
   *  (`free_runs_used`, `device_token_invalid`). Callers branch on this, never
   *  on `message` — the sentence is for people and may be reworded. */
  readonly code?: string;
  /** The free-run allowance and how much of it is spent, sent with a 402
   *  `free_runs_used`. Absent on every other error. */
  readonly limit?: number;
  readonly used?: number;

  /** `status` is the HTTP status, when there was one. Lets a caller tell "this
   *  run no longer exists" (404 — the server forgot it) from every other
   *  refusal without parsing `message`. */
  constructor(
    message: string,
    readonly status?: number,
    extra: { code?: string; limit?: number; used?: number } = {}
  ) {
    super(message);
    this.code = extra.code;
    this.limit = extra.limit;
    this.used = extra.used;
  }
}

/** The request never produced a usable response at all — connection refused,
 *  DNS failure, offline, blocked CORS preflight. Nothing is known to be wrong
 *  with the thing being fetched; the server simply could not be reached, which
 *  is why this case gets connectivity wording and a retry rather than a
 *  "could not load X" line. */
export class NetworkError extends Error {}

/** This browser will not let the app keep anything on the device — no
 *  IndexedDB at all, or one that refuses to open (some private modes). Not a
 *  failure of the app: History simply cannot be saved here, and everything
 *  else still works. */
export class StorageUnavailableError extends Error {}

/** Why a sign-in step failed, as the identity adapter can tell it. The hook
 *  turns this into the sentence; the adapter never writes copy. */
export type AuthFailureReason =
  | "invalid_email"
  | "invalid_code"
  | "rate_limited"
  | "unreachable"
  | "unavailable"
  | "unknown";

/** A sign-in step (send code, verify code) was refused or could not be
 *  attempted. `message` is the provider's own text, for logs only. */
export class AuthFlowError extends Error {
  constructor(
    readonly reason: AuthFailureReason,
    message: string
  ) {
    super(message);
  }
}
