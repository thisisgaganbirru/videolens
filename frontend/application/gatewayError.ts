import { ApiError, NetworkError } from "@/domain/errors";

/* One classification, used by every hook that awaits a gateway call.
   `useRunHistory` established this shape first; lifting it here rather than
   copying it into `useAnalysisRun` is the whole point — two copies would drift
   the moment a third error class appears, and the honest wording for "the
   server is down" is not something each feature should re-decide.

   It lives in `application/` and not in `domain/` on purpose: `domain/errors.ts`
   owns the *classes*, which are a contract between the gateway and its callers.
   This maps those classes onto a UI-shaped `{ kind, message }` and supplies a
   feature-specific fallback sentence — that is orchestration and copy, which is
   what `application/` is for. It stays free of React and of `fetch` so it can be
   called from anywhere in the layer. */

export type GatewayErrorKind = "unreachable" | "server" | "unknown";

export type GatewayError = {
  kind: GatewayErrorKind;
  message: string;
};

/**
 * Classify a rejected gateway call **by domain error class**, never by
 * inspecting the raw error's shape or text — `err instanceof TypeError` in a
 * hook or a component is exactly the layering violation the two error classes
 * exist to prevent.
 *
 * @param fallback the sentence for the "we genuinely don't know" case. It is
 *   the only copy a caller supplies: `NetworkError` already carries the honest
 *   connectivity sentence, and `ApiError` carries the backend's own `detail`,
 *   which is more specific than anything a caller could write.
 */
export function classifyGatewayError(err: unknown, fallback: string): GatewayError {
  if (err instanceof NetworkError) return { kind: "unreachable", message: err.message };
  if (err instanceof ApiError) return { kind: "server", message: err.message };
  return { kind: "unknown", message: fallback };
}
