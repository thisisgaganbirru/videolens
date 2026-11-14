import type { MediaSource, RunCreateResponse, RunListResponse, RunStatusResponse } from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import type { ApiKeyStore, RunsGateway } from "@/domain/ports";
import type { ApiClient } from "./apiClient";
import { UNREADABLE } from "./apiClient";

/* Transport failures (no response at all) are classified in `ApiClient`,
   the one place that calls `fetch` for the caller's own requests. */

/* An error body's `code` and a 402's `limit`/`used`, carried onto the
   `ApiError` so the hook can branch on `code` (`free_runs_used`,
   `device_token_invalid`) instead of matching the sentence. */
function errorExtras(body: unknown): { code?: string; limit?: number; used?: number } {
  if (typeof body !== "object" || body === null) return {};
  const b = body as Record<string, unknown>;
  return {
    code: typeof b.code === "string" ? b.code : undefined,
    limit: typeof b.limit === "number" ? b.limit : undefined,
    used: typeof b.used === "number" ? b.used : undefined,
  };
}

/* ---- Refinement 6 (RUN-16): what a refused POST /api/runs says ----------

   The backend's 4xx `detail` strings are written for people (terms, invalid
   link, media validation, 401/402 codes, and the 429 sentence in
   interface/api/app.py), so they are shown as sent. A 5xx is different: the
   API's own 503s (RunSchedulingError, QuotaExceededError,
   AnalysisUnavailableError) are curated sentences too, but a 500/502/504 is
   an unhandled exception, a proxy page or a gateway timeout, and its body is
   whatever that layer emitted. So a 5xx keeps its detail only when it is a
   503 carrying a short, one-line string; everything else gets one calm line. */
const CREATE_SERVER_TROUBLE = "The server had a problem starting this run. Try again in a moment.";
const CREATE_UNREADABLE_REFUSAL = "The server could not accept this run. Check the link or file and try again.";
const RATE_LIMITED = "You're going a bit fast.";
const DETAIL_MAX = 240;

/** `detail` when it is a plain sentence fit to show, else null. FastAPI's
 *  422 sends an array of objects here; a proxy may send HTML or JSON text. */
function userFacingDetail(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const detail = (body as Record<string, unknown>).detail;
  if (typeof detail !== "string") return null;
  const text = detail.trim();
  if (!text || text.length > DETAIL_MAX || /[\r\n]/.test(text)) return null;
  if (/^[[{<]/.test(text) || /traceback|exception|error:/i.test(text)) return null;
  return text;
}

/** Seconds to wait from a `Retry-After` header: delta-seconds or an HTTP
 *  date. Null when absent, unreadable or already past. Note that a browser
 *  only lets the page read this header cross-origin when the API lists it in
 *  `Access-Control-Expose-Headers`; until then this is null and the caller
 *  keeps its general wording. */
function retryAfterSeconds(value: string | null, now: number = Date.now()): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) {
    const seconds = Number(trimmed);
    return seconds > 0 ? seconds : null;
  }
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return null;
  const seconds = Math.ceil((at - now) / 1000);
  return seconds > 0 ? seconds : null;
}

/** "Try again in about a minute." / "… about 5 minutes." Never "0 minutes". */
function tryAgainIn(seconds: number): string {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return minutes === 1 ? "Try again in about a minute." : `Try again in about ${minutes} minutes.`;
}

/** The sentence for a refused run creation. */
function createRunFailureMessage(status: number, body: unknown, retryAfter: string | null): string {
  const detail = userFacingDetail(body);
  if (status === 429) {
    const wait = retryAfterSeconds(retryAfter);
    if (wait !== null) return `${RATE_LIMITED} ${tryAgainIn(wait)}`;
    return detail ?? `${RATE_LIMITED} Wait a minute and try again.`;
  }
  if (status >= 500) return status === 503 && detail ? detail : CREATE_SERVER_TROUBLE;
  return detail ?? CREATE_UNREADABLE_REFUSAL;
}

export class FetchRunsGateway implements RunsGateway {
  constructor(
    private readonly client: ApiClient,
    private readonly apiKeyStore: ApiKeyStore
  ) {}

  /* BYOK: the Gemini key travels ONLY on run creation (POST /api/runs), the
     one endpoint that reads it (backend interface/api/routes.py create_run).
     Polling a run and listing history never needed it, and before 2026-11-01
     it rode along on every one of those requests too — dozens per run, each a
     fresh copy of the secret on the wire for no reason.

     Everything else about who is calling (`X-Client-ID`, `X-Device-Token`,
     and since auth phase 2 the bearer token when someone is signed in) comes
     from `ApiClient`, on every request. */
  private send(path: string, init: RequestInit = {}, { withGeminiKey = false }: { withGeminiKey?: boolean } = {}) {
    const extra: Record<string, string> = {};
    if (withGeminiKey) {
      const geminiApiKey = this.apiKeyStore.get();
      if (geminiApiKey) extra["X-Gemini-Api-Key"] = geminiApiKey;
    }
    return this.client.send(path, init, extra);
  }

  /** A 2xx whose body will not parse is still a server-side problem — we
   *  reached it, it answered, the answer was unusable — so it stays an
   *  `ApiError`, just with its own specific message instead of a `detail`. */
  private async parse<T>(res: Response): Promise<T> {
    try {
      return (await res.json()) as T;
    } catch {
      throw new ApiError(UNREADABLE);
    }
  }

  async createRun(source: MediaSource): Promise<RunCreateResponse> {
    const formData = new FormData();
    if (source.file) formData.append("file", source.file);
    if (source.url) formData.append("url", source.url);
    formData.append("accept_terms", "true");

    const res = await this.send("/api/runs", { method: "POST", body: formData }, { withGeminiKey: true });

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(
        createRunFailureMessage(res.status, body, res.headers.get("Retry-After")),
        res.status,
        errorExtras(body)
      );
    }

    return this.parse<RunCreateResponse>(res);
  }

  async getRun(runId: string): Promise<RunStatusResponse> {
    const res = await this.send(`/api/runs/${runId}`);
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(body?.detail || `Could not fetch run status (${res.status})`, res.status);
    }
    return this.parse<RunStatusResponse>(res);
  }

  async listRuns(): Promise<RunListResponse> {
    const res = await this.send("/api/runs");
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(body?.detail || `Could not fetch run history (${res.status})`, res.status);
    }
    return this.parse<RunListResponse>(res);
  }
}
