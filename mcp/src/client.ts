import { openAsBlob } from "node:fs";
import { basename } from "node:path";

import type { Config } from "./config.js";
import type {
  AccountResponse,
  LibraryQuery,
  LibraryResponse,
  RunCreateResponse,
  RunListResponse,
  RunStatusResponse,
} from "./types.js";

/* A thin REST client over the same endpoints the web app calls - the MCP
   server adds no backend surface of its own. Same split the frontend's
   `apiClient.ts` makes: a request that never got an answer is a
   `NetworkError`; one the server answered with a refusal is an `ApiError`
   carrying the status and the server's own sentence, which is written for a
   person and is what the agent should relay. */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

export class VideoLensClient {
  constructor(
    private readonly config: Config,
    private readonly clientId: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  /** Which credential the server will see, for the agent's benefit. */
  describeAuth(): string {
    if (this.config.apiKey) return "workspace API key";
    return "your own Gemini key (anonymous, unmetered)";
  }

  private headers(): Record<string, string> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (this.config.apiKey) {
      headers["X-Api-Key"] = this.config.apiKey;
    } else {
      // Anonymous: the dotfile id scopes history; the Gemini key pays for
      // the model. With a workspace key the id is ignored server-side.
      headers["X-Client-ID"] = this.clientId;
    }
    if (this.config.geminiApiKey) headers["X-Gemini-Api-Key"] = this.config.geminiApiKey;
    return headers;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const url = `${this.config.apiUrl}${path}`;
    let response: Response;
    try {
      response = await this.fetchImpl(url, { ...init, headers: { ...this.headers(), ...(init.headers ?? {}) } });
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new NetworkError(`Could not reach the VideoLens API at ${this.config.apiUrl}: ${reason}`);
    }
    if (!response.ok) throw await this.refusal(response);
    if (response.status === 204) return undefined as T;
    try {
      return (await response.json()) as T;
    } catch {
      throw new ApiError(`The API answered ${response.status} with an unreadable body.`, response.status);
    }
  }

  private async refusal(response: Response): Promise<ApiError> {
    let detail = `The API answered ${response.status}.`;
    let code: string | null = null;
    try {
      const body = (await response.json()) as { detail?: unknown; code?: unknown };
      if (typeof body.detail === "string" && body.detail) detail = body.detail;
      else if (Array.isArray(body.detail)) detail = JSON.stringify(body.detail);
      if (typeof body.code === "string") code = body.code;
    } catch {
      // Keep the status-only sentence.
    }
    return new ApiError(detail, response.status, code);
  }

  async createRunFromUrl(url: string): Promise<RunCreateResponse> {
    const form = new FormData();
    form.append("url", url);
    form.append("accept_terms", "true");
    return this.request<RunCreateResponse>("/api/runs", { method: "POST", body: form });
  }

  async createRunFromFile(filePath: string): Promise<RunCreateResponse> {
    const form = new FormData();
    // Streamed from disk: a 200 MB upload never has to sit in memory.
    form.append("file", await openAsBlob(filePath), basename(filePath));
    form.append("accept_terms", "true");
    return this.request<RunCreateResponse>("/api/runs", { method: "POST", body: form });
  }

  async getRun(runId: string): Promise<RunStatusResponse> {
    return this.request<RunStatusResponse>(`/api/runs/${encodeURIComponent(runId)}`);
  }

  async listRuns(): Promise<RunListResponse> {
    return this.request<RunListResponse>("/api/runs");
  }

  async searchLibrary(query: LibraryQuery): Promise<LibraryResponse> {
    const params = new URLSearchParams();
    if (query.query) params.set("query", query.query);
    if (query.platform) params.set("platform", query.platform);
    if (query.since) params.set("since", query.since);
    if (query.until) params.set("until", query.until);
    if (query.limit != null) params.set("limit", String(query.limit));
    if (query.offset != null) params.set("offset", String(query.offset));
    const suffix = params.size ? `?${params.toString()}` : "";
    return this.request<LibraryResponse>(`/api/library${suffix}`);
  }

  async account(): Promise<AccountResponse> {
    return this.request<AccountResponse>("/api/me");
  }

  /** Poll until the run settles or the budget runs out. Returns the last
   *  state either way; the caller reads `status` to know which it was. */
  async waitForRun(
    runId: string,
    waitSeconds: number,
    onStage?: (stage: string | null, status: string) => void,
  ): Promise<RunStatusResponse> {
    const deadline = Date.now() + waitSeconds * 1000;
    let delayMs = 2000;
    let lastStage: string | null | undefined;
    for (;;) {
      const run = await this.getRun(runId);
      if (run.status === "complete" || run.status === "failed") return run;
      if (onStage && run.stage !== lastStage) {
        lastStage = run.stage;
        onStage(run.stage, run.status);
      }
      if (Date.now() >= deadline) return run;
      await new Promise((resolve) => setTimeout(resolve, Math.min(delayMs, Math.max(0, deadline - Date.now()))));
      // Back off gently: a two-hour video does not need a poll every two seconds.
      delayMs = Math.min(delayMs * 1.5, 15000);
    }
  }
}
