import { readFile } from "node:fs/promises";
import { basename } from "node:path";

export interface RunCreateResponse {
  run_id: string;
  status: "queued" | "processing" | "complete" | "failed";
}

export interface VideoAnalysis {
  title: string;
  summary: string;
  transcript: string;
  screen_text: string;
  markdown: string;
}

export interface RunStatusResponse {
  run_id: string;
  status: "queued" | "processing" | "complete" | "failed";
  stage?: string | null;
  result?: VideoAnalysis | null;
  error?: string | null;
}

export interface RunSummary {
  run_id: string;
  status: "queued" | "processing" | "complete" | "failed";
  title?: string | null;
  created_at: string;
}

export class VideoLensApiError extends Error {}

export class VideoLensClient {
  constructor(
    private readonly baseUrl: string,
    private readonly geminiApiKey: string,
    private readonly clientId: string,
  ) {}

  private headers(extra?: Record<string, string>): Record<string, string> {
    return {
      "X-Client-ID": this.clientId,
      "X-Gemini-Api-Key": this.geminiApiKey,
      ...extra,
    };
  }

  async createRun(input: { filePath?: string; url?: string }): Promise<RunCreateResponse> {
    const form = new FormData();
    form.set("accept_terms", "true");

    if (input.filePath) {
      const bytes = await readFile(input.filePath);
      form.set("file", new Blob([bytes]), basename(input.filePath));
    } else if (input.url) {
      form.set("url", input.url);
    } else {
      throw new VideoLensApiError("Either file_path or url is required.");
    }

    const response = await fetch(`${this.baseUrl}/api/runs`, {
      method: "POST",
      headers: this.headers(),
      body: form,
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new VideoLensApiError(`Failed to create run (${response.status}): ${detail}`);
    }

    return (await response.json()) as RunCreateResponse;
  }

  async getRun(runId: string): Promise<RunStatusResponse> {
    const response = await fetch(`${this.baseUrl}/api/runs/${runId}`, {
      headers: this.headers(),
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new VideoLensApiError(`Failed to fetch run ${runId} (${response.status}): ${detail}`);
    }

    return (await response.json()) as RunStatusResponse;
  }

  async listRuns(): Promise<RunSummary[]> {
    const response = await fetch(`${this.baseUrl}/api/runs`, {
      headers: this.headers(),
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new VideoLensApiError(`Failed to list runs (${response.status}): ${detail}`);
    }

    const body = (await response.json()) as { runs: RunSummary[] };
    return body.runs;
  }
}
