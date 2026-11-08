import { ApiError, NetworkError } from "@/domain/errors";
import type { AuthSession, CallerIdentity, DeviceTokenStore, ServerAuthStatus } from "@/domain/ports";
import { API_BASE_URL } from "./apiBase";
import { getClientId } from "./clientId";

/* The transport every gateway that speaks for *this caller* shares (auth
   phase 2). It assembles the identity the backend's `get_principal` reads:

   - `X-Client-ID` always, so an anonymous caller keeps their own runs;
   - `X-Device-Token` always when this device has one (it counts free runs
     and is not a secret);
   - `Authorization: Bearer <access token>` only when someone is signed in
     **and** this server's `auth` capability is `ok`. The backend reads a
     bearer *instead of* the client id, so sending one to a server without a
     matching verifier would turn every caller route into a 401/503. With the
     report still in flight and a session present, a request waits for it
     (bounded); unknown after that means anonymous.

   When a session exists and the server takes tokens but no token can be had
   right now, the request fails as a `NetworkError` instead of going out
   anonymous: an anonymous poll of a run the person owns answers 404, which
   History would otherwise read as "expired". The poll's reconnect retries.

   The Gemini key is not here: it travels only with run creation, which adds
   it itself (runsGateway). The capabilities and release gateways do not use
   this at all; they describe the server, not the caller. */

export const UNREACHABLE = "Can't reach the server. It may be offline, or your connection dropped.";
export const UNREADABLE = "The server replied with something this app could not read.";
const SIGN_IN_UNCONFIRMED =
  "Your sign-in could not be confirmed just now. Check your connection; the app will try again.";

/** How long a signed-in request waits for the capability report. */
const SERVER_AUTH_WAIT_MS = 4000;

export const ANONYMOUS_OWNER = "anonymous";

export class ApiClient implements CallerIdentity {
  private owner: string | null = null;

  constructor(
    private readonly auth: AuthSession,
    private readonly deviceTokenStore: DeviceTokenStore,
    private readonly serverAuth: ServerAuthStatus
  ) {}

  lastOwner(): string | null {
    return this.owner;
  }

  /** The bearer, or null to go out anonymous. Throws `NetworkError` when it
   *  must not go out anonymous and cannot go out signed in. */
  private async bearer(): Promise<string | null> {
    if (!this.auth.enabled || !this.auth.hasSession()) return null;
    const state = await this.serverAuth.settled(SERVER_AUTH_WAIT_MS);
    if (state !== "ok") return null;
    try {
      return await this.auth.getToken();
    } catch {
      throw new NetworkError(SIGN_IN_UNCONFIRMED);
    }
  }

  private async identityHeaders(): Promise<Record<string, string>> {
    const headers: Record<string, string> = { "X-Client-ID": getClientId() };
    const deviceToken = this.deviceTokenStore.get();
    if (deviceToken) headers["X-Device-Token"] = deviceToken;
    const token = await this.bearer();
    const userId = token ? this.auth.user()?.id : null;
    if (token) headers["Authorization"] = `Bearer ${token}`;
    /* Unknown (null) rather than a guess if a token came without a user. */
    this.owner = token ? (userId ? `user:${userId}` : null) : ANONYMOUS_OWNER;
    return headers;
  }

  /** Transport only: resolves with whatever HTTP response came back (status
   *  untouched), throws `NetworkError` when none came back at all. `extra`
   *  headers are added last (the Gemini key on run creation, a JSON
   *  content type). */
  async send(path: string, init: RequestInit = {}, extra: Record<string, string> = {}): Promise<Response> {
    const headers = { ...(await this.identityHeaders()), ...extra };
    try {
      return await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
    } catch {
      throw new NetworkError(UNREACHABLE);
    }
  }

  /** A 2xx whose body will not parse is still a server-side problem, so it
   *  stays an `ApiError`, with its own message instead of a `detail`. */
  async parse<T>(res: Response): Promise<T> {
    try {
      return (await res.json()) as T;
    } catch {
      throw new ApiError(UNREADABLE, res.status);
    }
  }

  /** A non-2xx as an `ApiError` carrying the backend's own `detail` (when it
   *  is a string) and `code`, else `fallback (status)`. */
  async reject(res: Response, fallback: string): Promise<never> {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : null;
    const code = typeof body?.code === "string" ? body.code : undefined;
    throw new ApiError(detail || `${fallback} (${res.status})`, res.status, { code });
  }

  async json<T>(path: string, init: RequestInit, fallback: string): Promise<T> {
    const res = await this.send(path, init);
    if (!res.ok) await this.reject(res, fallback);
    return this.parse<T>(res);
  }

  async jsonBody<T>(path: string, method: string, body: unknown, fallback: string): Promise<T> {
    const res = await this.send(path, { method, body: JSON.stringify(body) }, { "Content-Type": "application/json" });
    if (!res.ok) await this.reject(res, fallback);
    return this.parse<T>(res);
  }
}
