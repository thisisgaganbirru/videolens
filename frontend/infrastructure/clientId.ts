/* `X-Client-ID`: a random id made in this browser that scopes which runs it
   can see. Not a secret and not quota. Lived inside `runsGateway.ts` until
   `freeRunsGateway.ts` became the second adapter to send it (Phase 5b) — one
   copy, so the two can never disagree about who the caller is. */

const CLIENT_ID_KEY = "videolens-client-id";

export function getClientId(): string {
  let clientId = window.localStorage.getItem(CLIENT_ID_KEY);
  if (!clientId) {
    clientId = crypto.randomUUID();
    window.localStorage.setItem(CLIENT_ID_KEY, clientId);
  }
  return clientId;
}
