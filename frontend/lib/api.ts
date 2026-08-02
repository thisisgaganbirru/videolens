import type { RunCreateResponse, RunStatusResponse } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {}

export type MediaSource = { file: File; url?: never } | { url: string; file?: never };

export async function createRun(source: MediaSource): Promise<RunCreateResponse> {
  const formData = new FormData();
  if (source.file) formData.append("file", source.file);
  if (source.url) formData.append("url", source.url);

  const res = await fetch(`${API_BASE_URL}/api/runs`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.detail || `Could not create run (${res.status})`);
  }

  return res.json();
}

export async function getRun(runId: string): Promise<RunStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${runId}`);
  if (!res.ok) {
    throw new ApiError(`Could not fetch run status (${res.status})`);
  }
  return res.json();
}
