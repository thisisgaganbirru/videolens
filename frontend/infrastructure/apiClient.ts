import { ApiError, NetworkError } from "@/domain/errors";
import type { ApiKeyStore, AuthSession } from "@/domain/ports";
import { API_BASE_URL } from "./apiBase";

const CLIENT_ID_KEY = "videolens-client-id";

/* The one place in the app that knows the difference between "the server said
   no" and "there was no server to say anything". `fetch` rejects (with a
   TypeError, but that detail stops here) when the connection is refused, DNS
   fails, the device is offline, or a CORS preflight is blocked; it resolves
   for every HTTP status, including 4xx/5xx. Classifying it here is what lets
   hooks and components stay out of the business of guessing. */
export const UNREACHABLE = "Can't reach the server. It may be offline, or your connection dropped.";
export const UNREADABLE = "The server replied with something this app could not read.";

function getClientId(): string {
  let clientId = window.localStorage.getItem(CLIENT_ID_KEY);
  if (!clientId) {
    clientId = crypto.randomUUID();
    window.localStorage.setItem(CLIENT_ID_KEY, clientId);
  }
  return clientId;
}

/**
 * Transport shared by every gateway that speaks for *this caller*.
 *
 * It assembles the identity the backend's `get_principal` reads, strongest
 * first: a bearer token when someone is signed in, the BYOK Gemini key when
 * one is stored, and always `X-Client-ID` so an anonymous caller keeps their
 * own history. The capabilities and release gateways deliberately do not use
 * it — they describe the server, not the caller.
 */
export class ApiClient {
  constructor(
    private readonly apiKeyStore: ApiKeyStore,
    private readonly auth: AuthSession,
  ) {}

  private async requestHeaders(): Promise<Record<string, string>> {
    const headers: Record<string, string> = { "X-Client-ID": getClientId() };
    const geminiApiKey = this.apiKeyStore.get();
    if (geminiApiKey) headers["X-Gemini-Api-Key"] = geminiApiKey;
    const token = await this.auth.getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return headers;
  }

  /** Transport layer only: resolves with whatever HTTP response came back
   *  (status untouched), throws `NetworkError` when none came back at all. */
  async send(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = { ...(await this.requestHeaders()), ...(init.headers as Record<string, string> | undefined) };
    try {
      return await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
    } catch {
      throw new NetworkError(UNREACHABLE);
    }
  }

  /** A 2xx whose body will not parse is still a server-side problem — we
   *  reached it, it answered, the answer was unusable — so it stays an
   *  `ApiError`, just with its own specific message instead of a `detail`. */
  async parse<T>(res: Response): Promise<T> {
    try {
      return (await res.json()) as T;
    } catch {
      throw new ApiError(UNREADABLE, { status: res.status });
    }
  }

  /** Turns a non-2xx into an `ApiError` carrying the backend's own `detail`
   *  and, where it sent one, its machine-readable `code`. */
  async reject(res: Response, fallback: string): Promise<never> {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : null;
    const code = typeof body?.code === "string" ? body.code : null;
    throw new ApiError(detail || `${fallback} (${res.status})`, { code, status: res.status });
  }

  async json<T>(path: string, init: RequestInit, fallback: string): Promise<T> {
    const res = await this.send(path, init);
    if (!res.ok) await this.reject(res, fallback);
    return this.parse<T>(res);
  }

  async jsonBody<T>(path: string, method: string, body: unknown, fallback: string): Promise<T> {
    return this.json<T>(
      path,
      { method, body: JSON.stringify(body), headers: { "Content-Type": "application/json" } },
      fallback,
    );
  }
}
