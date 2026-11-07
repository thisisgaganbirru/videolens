/* `X-Client-ID`: a random id made in this browser that scopes which runs it
   can see. Not a secret and not quota. Lived inside `runsGateway.ts` until
   `freeRunsGateway.ts` became the second adapter to send it (Phase 5b) — one
   copy, so the two can never disagree about who the caller is.

   Storage can throw (Safari private mode, blocked site data, a sandboxed
   WebView). Refinement 1 (#5): fall back to an id that lives for this page
   load, so the tool still works; it just can't see runs from a previous
   visit, which it couldn't have read anyway. */

const CLIENT_ID_KEY = "videolens-client-id";

let memoryClientId: string | null = null;

export function getClientId(): string {
  try {
    let clientId = window.localStorage.getItem(CLIENT_ID_KEY);
    if (!clientId) {
      clientId = crypto.randomUUID();
      window.localStorage.setItem(CLIENT_ID_KEY, clientId);
    }
    return clientId;
  } catch {
    memoryClientId ??= crypto.randomUUID();
    return memoryClientId;
  }
}
