import type { RunCreateResponse, RunListResponse, RunStatusResponse } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {}

export type MediaSource = { file: File; url?: never } | { url: string; file?: never };

const CLIENT_ID_KEY = "videolens-client-id";
const GEMINI_API_KEY_STORAGE_KEY = "videolens-gemini-api-key";

function getClientId() {
  let clientId = window.localStorage.getItem(CLIENT_ID_KEY);
  if (!clientId) {
    clientId = crypto.randomUUID();
    window.localStorage.setItem(CLIENT_ID_KEY, clientId);
  }
  return clientId;
}

// Bring-your-own-key: kept only on-device. Sent with run creation so that
// user's own quota is spent instead of the shared one - never written
// anywhere else, never logged.
export function getStoredGeminiApiKey(): string {
  return window.localStorage.getItem(GEMINI_API_KEY_STORAGE_KEY) || "";
}

export function setStoredGeminiApiKey(apiKey: string): void {
  const trimmed = apiKey.trim();
  if (trimmed) {
    window.localStorage.setItem(GEMINI_API_KEY_STORAGE_KEY, trimmed);
  } else {
    window.localStorage.removeItem(GEMINI_API_KEY_STORAGE_KEY);
  }
}

function requestHeaders(): HeadersInit {
  const headers: Record<string, string> = { "X-Client-ID": getClientId() };
  const geminiApiKey = getStoredGeminiApiKey();
  if (geminiApiKey) headers["X-Gemini-Api-Key"] = geminiApiKey;
  return headers;
}

export async function createRun(source: MediaSource): Promise<RunCreateResponse> {
  const formData = new FormData();
  if (source.file) formData.append("file", source.file);
  if (source.url) formData.append("url", source.url);
  formData.append("accept_terms", "true");

  const res = await fetch(`${API_BASE_URL}/api/runs`, {
    method: "POST",
    body: formData,
    headers: requestHeaders(),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.detail || `Could not create run (${res.status})`);
  }

  return res.json();
}

export async function getRun(runId: string): Promise<RunStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${runId}`, {
    headers: requestHeaders(),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.detail || `Could not fetch run status (${res.status})`);
  }
  return res.json();
}

export async function listRuns(): Promise<RunListResponse> {
  const res = await fetch(`${API_BASE_URL}/api/runs`, {
    headers: requestHeaders(),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.detail || `Could not fetch run history (${res.status})`);
  }
  return res.json();
}
