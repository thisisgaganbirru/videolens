import type { MediaSource, RunCreateResponse, RunListResponse, RunStatusResponse } from "@/domain/entities";
import type { RunsGateway } from "@/domain/ports";
import type { ApiClient } from "./apiClient";

/* The transport — identity headers, `NetworkError` vs `ApiError`, the
   unreadable-body case — moved to `apiClient.ts` when the account and library
   gateways needed the same thing. This file is now only the three run
   endpoints and their fallback sentences. */
export class FetchRunsGateway implements RunsGateway {
  constructor(private readonly client: ApiClient) {}

  async createRun(source: MediaSource): Promise<RunCreateResponse> {
    const formData = new FormData();
    if (source.file) formData.append("file", source.file);
    if (source.url) formData.append("url", source.url);
    formData.append("accept_terms", "true");
    return this.client.json<RunCreateResponse>(
      "/api/runs",
      { method: "POST", body: formData },
      "Could not create run",
    );
  }

  async getRun(runId: string): Promise<RunStatusResponse> {
    return this.client.json<RunStatusResponse>(`/api/runs/${runId}`, {}, "Could not fetch run status");
  }

  async listRuns(): Promise<RunListResponse> {
    return this.client.json<RunListResponse>("/api/runs", {}, "Could not fetch run history");
  }
}
