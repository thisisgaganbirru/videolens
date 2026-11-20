import { ApiError, NetworkError } from "@/domain/errors";
import type {
  AccountHoldNotice,
  AccountHoldSource,
  AuthSession,
  CallerIdentity,
  DeviceTokenStore,
  ServerAuthStatus,
} from "@/domain/ports";
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
     (bounded).

   A request with a session stored never goes out anonymous (2026-11-20).
   When the server's report is still unknown after the wait, or the server
   takes tokens but no token can be had right now, it fails as a
   `SignInUnconfirmedError` instead: an anonymous create would be filed in
   History as `anonymous` and outlive the sign-out, and an anonymous poll of
   a run the person owns answers 404. A poll's reconnect retries; a create
   says so and the person sends it again. Nobody signed in means no wait at
   all: anonymous requests are never delayed by this.

   The Gemini key is not here: it travels only with run creation, which adds
   it itself (runsGateway). The capabilities and release gateways do not use
   this at all; they describe the server, not the caller. */

export const UNREACHABLE = "Can't reach the server. It may be offline, or your connection dropped.";
export const UNREADABLE = "The server replied with something this app could not read.";
const SIGN_IN_UNCONFIRMED =
  "Your sign-in could not be confirmed just now. Check your connection; the app will try again.";

/** No HTTP response came back at all: `fetch` itself failed. The only
 *  `NetworkError` that says anything about the bytes on the wire. */
export class FetchFailedError extends NetworkError {}

/** A session is stored but the request could not go out signed in (the
 *  server's sign-in report is not known yet, or no token could be had). Thrown
 *  before anything is sent. */
export class SignInUnconfirmedError extends NetworkError {}

/** Seconds to wait from a `Retry-After` header: delta-seconds or an HTTP
 *  date. Null when absent, unreadable or already past. Note that a browser
 *  only lets the page read this header cross-origin when the API lists it in
 *  `Access-Control-Expose-Headers`; until then this is null and the caller
 *  keeps its general wording. */
export function retryAfterSeconds(value: string | null, now: number = Date.now()): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) {
    const seconds = Number(trimmed);
    return seconds > 0 ? seconds : null;
  }
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return null;
  const seconds = Math.ceil((at - now) / 1000);
  return seconds > 0 ? seconds : null;
}

/** How long a request with a session stored waits for the capability
 *  report before it fails (never before it goes out anonymous). */
const SERVER_AUTH_WAIT_MS = 8000;

export const ANONYMOUS_OWNER = "anonymous";

/** The 410 a held account gets on every identity-resolving route. */
export const ACCOUNT_PENDING_DELETION = "account_pending_deletion";

export class ApiClient implements CallerIdentity, AccountHoldSource {
  private owner: string | null = null;
  private readonly holdListeners = new Set<(notice: AccountHoldNotice) => void>();

  constructor(
    private readonly auth: AuthSession,
    private readonly deviceTokenStore: DeviceTokenStore,
    private readonly serverAuth: ServerAuthStatus
  ) {}

  lastOwner(): string | null {
    return this.owner;
  }

  /** The deletion hold (2026-11-14): every caller gateway sends through
   *  here, so this is the one place that hears a held account's 410,
   *  whichever request it answered. */
  subscribe(listener: (notice: AccountHoldNotice) => void): () => void {
    this.holdListeners.add(listener);
    return () => {
      this.holdListeners.delete(listener);
    };
  }

  /** Reads a 410 from a clone, so the caller still gets the whole body. */
  private async noticeHold(res: Response, owner: string | null): Promise<void> {
    if (res.status !== 410 || this.holdListeners.size === 0) return;
    const body = await res.clone().json().catch(() => null);
    if (body?.code !== ACCOUNT_PENDING_DELETION) return;
    const notice: AccountHoldNotice = {
      owner,
      purgeAt: typeof body.purge_at === "string" ? body.purge_at : null,
    };
    this.holdListeners.forEach((listener) => listener(notice));
  }

  /** The bearer, or null to go out anonymous. Throws
   *  `SignInUnconfirmedError` when it must not go out anonymous (a session is
   *  stored) and cannot go out signed in. */
  private async bearer(): Promise<string | null> {
    if (!this.auth.enabled || !this.auth.hasSession()) return null;
    const state = await this.serverAuth.settled(SERVER_AUTH_WAIT_MS);
    /* `off`: this server does not take tokens at all, so everyone is
       anonymous to it, signed in or not. */
    if (state === "off") return null;
    if (state !== "ok") throw new SignInUnconfirmedError(SIGN_IN_UNCONFIRMED);
    try {
      return await this.auth.getToken();
    } catch {
      throw new SignInUnconfirmedError(SIGN_IN_UNCONFIRMED);
    }
  }

  /** The headers and the owner they speak for, together: the owner a
   *  response is filed under is the one this request went out as, never a
   *  shared field another request may have moved on since. */
  private async identityHeaders(): Promise<{ headers: Record<string, string>; owner: string | null }> {
    const headers: Record<string, string> = { "X-Client-ID": getClientId() };
    const deviceToken = this.deviceTokenStore.get();
    if (deviceToken) headers["X-Device-Token"] = deviceToken;
    const token = await this.bearer();
    const userId = token ? this.auth.user()?.id : null;
    if (token) headers["Authorization"] = `Bearer ${token}`;
    /* Unknown (null) rather than a guess if a token came without a user.
       History never creates a row for an unknown owner. */
    const owner = token ? (userId ? `user:${userId}` : null) : ANONYMOUS_OWNER;
    this.owner = owner;
    return { headers, owner };
  }

  /** Transport only: resolves with whatever HTTP response came back (status
   *  untouched), throws `NetworkError` when none came back at all. `extra`
   *  headers are added last (the Gemini key on run creation, a JSON
   *  content type). An aborted request rethrows the `AbortError` itself, so
   *  a cancel is never mistaken for the server being down. */
  async send(path: string, init: RequestInit = {}, extra: Record<string, string> = {}): Promise<Response> {
    return (await this.sendAs(path, init, extra)).res;
  }

  /** `send`, plus the identity this request went out as. A caller that files
   *  the answer under an owner (History) takes it from here, not from
   *  `lastOwner()`, which another request may have moved on since. */
  async sendAs(
    path: string,
    init: RequestInit = {},
    extra: Record<string, string> = {}
  ): Promise<{ res: Response; owner: string | null }> {
    const identity = await this.identityHeaders();
    const headers = { ...identity.headers, ...extra };
    const owner = identity.owner;
    let res: Response;
    try {
      res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
    } catch (error) {
      if (init.signal?.aborted) throw error;
      throw new FetchFailedError(UNREACHABLE);
    }
    await this.noticeHold(res, owner);
    return { res, owner };
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
   *  is a string), `code` and `Retry-After`, else `fallback (status)`. */
  async reject(res: Response, fallback: string): Promise<never> {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : null;
    const code = typeof body?.code === "string" ? body.code : undefined;
    const purgeAt = typeof body?.purge_at === "string" ? body.purge_at : undefined;
    const retryAfter = retryAfterSeconds(res.headers.get("Retry-After")) ?? undefined;
    throw new ApiError(detail || `${fallback} (${res.status})`, res.status, { code, purgeAt, retryAfter });
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
