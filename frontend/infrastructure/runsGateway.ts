import type { MediaSource, RunCreateResponse, RunListResponse, RunStatusResponse } from "@/domain/entities";
import { ApiError, NetworkError } from "@/domain/errors";
import type { ApiKeyStore, RunsGateway } from "@/domain/ports";
import { API_BASE_URL } from "./apiBase";

const CLIENT_ID_KEY = "videolens-client-id";

/* The one place in the app that knows the difference between "the server said
   no" and "there was no server to say anything". `fetch` rejects (with a
   TypeError, but that detail stops here) when the connection is refused, DNS
   fails, the device is offline, or a CORS preflight is blocked; it resolves
   for every HTTP status, including 4xx/5xx. Classifying it here is what lets
   hooks and components stay out of the business of guessing. */
const UNREACHABLE = "Can't reach the server. It may be offline, or your connection dropped.";
const UNREADABLE = "The server replied with something this app could not read.";

function getClientId(): string {
  let clientId = window.localStorage.getItem(CLIENT_ID_KEY);
  if (!clientId) {
    clientId = crypto.randomUUID();
    window.localStorage.setItem(CLIENT_ID_KEY, clientId);
  }
  return clientId;
}

export class FetchRunsGateway implements RunsGateway {
  constructor(private readonly apiKeyStore: ApiKeyStore) {}

  private requestHeaders(): HeadersInit {
    const headers: Record<string, string> = { "X-Client-ID": getClientId() };
    const geminiApiKey = this.apiKeyStore.get();
    if (geminiApiKey) headers["X-Gemini-Api-Key"] = geminiApiKey;
    return headers;
  }

  /** Transport layer only: resolves with whatever HTTP response came back
   *  (status untouched), throws `NetworkError` when none came back at all. */
  private async send(path: string, init: RequestInit = {}): Promise<Response> {
    try {
      return await fetch(`${API_BASE_URL}${path}`, { ...init, headers: this.requestHeaders() });
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

    const res = await this.send("/api/runs", { method: "POST", body: formData });

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(body?.detail || `Could not create run (${res.status})`);
    }

    return this.parse<RunCreateResponse>(res);
  }

  async getRun(runId: string): Promise<RunStatusResponse> {
    const res = await this.send(`/api/runs/${runId}`);
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(body?.detail || `Could not fetch run status (${res.status})`);
    }
    return this.parse<RunStatusResponse>(res);
  }

  async listRuns(): Promise<RunListResponse> {
    const res = await this.send("/api/runs");
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(body?.detail || `Could not fetch run history (${res.status})`);
    }
    return this.parse<RunListResponse>(res);
  }
}
