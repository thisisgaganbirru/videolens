import type { MediaSource, RunCreateResponse, RunListResponse, RunStatusResponse } from "@/domain/entities";
import { ApiError, NetworkError } from "@/domain/errors";
import type { ApiKeyStore, DeviceTokenStore, RunsGateway } from "@/domain/ports";
import { API_BASE_URL } from "./apiBase";
import { getClientId } from "./clientId";

/* The one place in the app that knows the difference between "the server said
   no" and "there was no server to say anything". `fetch` rejects (with a
   TypeError, but that detail stops here) when the connection is refused, DNS
   fails, the device is offline, or a CORS preflight is blocked; it resolves
   for every HTTP status, including 4xx/5xx. Classifying it here is what lets
   hooks and components stay out of the business of guessing. */
const UNREACHABLE = "Can't reach the server. It may be offline, or your connection dropped.";
const UNREADABLE = "The server replied with something this app could not read.";

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

export class FetchRunsGateway implements RunsGateway {
  constructor(
    private readonly apiKeyStore: ApiKeyStore,
    private readonly deviceTokenStore: DeviceTokenStore
  ) {}

  /* BYOK: the Gemini key travels ONLY on run creation (POST /api/runs), the
     one endpoint that reads it (backend interface/api/routes.py create_run).
     Polling a run and listing history never needed it, and before 2026-11-01
     it rode along on every one of those requests too — dozens per run, each a
     fresh copy of the secret on the wire for no reason. `X-Client-ID` still
     goes everywhere: it scopes which runs a caller can see.

     `X-Device-Token` (Phase 5b) rides on run creation too, and only there — it
     is what the server counts a free run against. Sent alongside a key as
     well; the server simply does not count bring-your-own-key runs. */
  private requestHeaders({ withGeminiKey }: { withGeminiKey: boolean }): HeadersInit {
    const headers: Record<string, string> = { "X-Client-ID": getClientId() };
    if (withGeminiKey) {
      const geminiApiKey = this.apiKeyStore.get();
      if (geminiApiKey) headers["X-Gemini-Api-Key"] = geminiApiKey;
      const deviceToken = this.deviceTokenStore.get();
      if (deviceToken) headers["X-Device-Token"] = deviceToken;
    }
    return headers;
  }

  /** Transport layer only: resolves with whatever HTTP response came back
   *  (status untouched), throws `NetworkError` when none came back at all.
   *  `withGeminiKey` defaults to false; only `createRun` passes true. */
  private async send(
    path: string,
    init: RequestInit = {},
    { withGeminiKey = false }: { withGeminiKey?: boolean } = {}
  ): Promise<Response> {
    try {
      return await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers: this.requestHeaders({ withGeminiKey }),
      });
    } catch {
      throw new NetworkError(UNREACHABLE);
    }
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
      throw new ApiError(body?.detail || `Could not create run (${res.status})`, res.status, errorExtras(body));
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
