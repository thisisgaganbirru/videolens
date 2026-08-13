import type { MediaSource, RunCreateResponse, RunListResponse, RunStatusResponse } from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import type { ApiKeyStore, RunsGateway } from "@/domain/ports";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const CLIENT_ID_KEY = "videolens-client-id";

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

  async createRun(source: MediaSource): Promise<RunCreateResponse> {
    const formData = new FormData();
    if (source.file) formData.append("file", source.file);
    if (source.url) formData.append("url", source.url);
    formData.append("accept_terms", "true");

    const res = await fetch(`${API_BASE_URL}/api/runs`, {
      method: "POST",
      body: formData,
      headers: this.requestHeaders(),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(body?.detail || `Could not create run (${res.status})`);
    }

    return res.json();
  }

  async getRun(runId: string): Promise<RunStatusResponse> {
    const res = await fetch(`${API_BASE_URL}/api/runs/${runId}`, {
      headers: this.requestHeaders(),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(body?.detail || `Could not fetch run status (${res.status})`);
    }
    return res.json();
  }

  async listRuns(): Promise<RunListResponse> {
    const res = await fetch(`${API_BASE_URL}/api/runs`, {
      headers: this.requestHeaders(),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(body?.detail || `Could not fetch run history (${res.status})`);
    }
    return res.json();
  }
}
