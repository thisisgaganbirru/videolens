/* The two ways a gateway call can fail. They are separate classes because the
   honest sentence for each is different, and because only the adapter that
   calls `fetch` can tell them apart — hooks and components must never sniff
   `err instanceof TypeError` or match on message text to work it out. */

/** The server answered and the answer was a problem. `message` carries the
 *  backend's own `detail` where it sent one, so it is already specific and
 *  should be shown as-is rather than replaced with a generic line. */
export class ApiError extends Error {}

/** The request never produced a usable response at all — connection refused,
 *  DNS failure, offline, blocked CORS preflight. Nothing is known to be wrong
 *  with the thing being fetched; the server simply could not be reached, which
 *  is why this case gets connectivity wording and a retry rather than a
 *  "could not load X" line. */
export class NetworkError extends Error {}
