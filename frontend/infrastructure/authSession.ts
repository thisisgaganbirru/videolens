import type { Session, SupabaseClient } from "@supabase/supabase-js";
import { Capacitor } from "@capacitor/core";
import type { AuthUser } from "@/domain/entities";
import { AuthFlowError, type AuthFailureReason } from "@/domain/errors";
import type { AuthSession } from "@/domain/ports";
import { providerStorageKey } from "./authSessionStamp";

/* The identity provider, behind the `AuthSession` port (auth phase 2).

   Config-gated on `NEXT_PUBLIC_SUPABASE_URL` and
   `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`. With either one blank the container
   builds `NullAuthSession`, which is what "sign-in is not set up on this
   deployment" looks like to the rest of the app: no token on any request, no
   user, and no Account tab. `@supabase/supabase-js` is loaded with a dynamic
   `import()` so a deployment that never configures it never ships it to the
   page; the chunk is fetched the first time a request asks for a token.

   Nothing outside this file names Supabase. The hooks see `AuthUser` and a
   token; the API sees a bearer JWT it verifies against the project's JWKS
   (`AUTH_JWKS_URL` on the backend). Swapping providers is this file plus the
   backend's three `AUTH_*` variables.

   The session (access + refresh token) is kept in this origin's localStorage,
   sandboxed per app in the Capacitor WebView, consistent with the BYOK key.
   Moving the refresh token to encrypted native storage is a later hardening
   step (docs/auth-plan.md, "Android specifics"). */

/** How long `getToken` waits for the provider to load. With no session at
 *  all the request then goes out anonymous; with one, it fails (see the
 *  port) so a run the person owns is never asked for as someone else. */
const LOAD_WAIT_MS = 4000;

export class NullAuthSession implements AuthSession {
  readonly enabled = false;

  async load(): Promise<void> {}

  user(): AuthUser | null {
    return null;
  }

  hasSession(): boolean {
    return false;
  }

  async getToken(): Promise<string | null> {
    return null;
  }

  async requestEmailCode(): Promise<void> {
    throw new AuthFlowError("unavailable", "sign-in is not configured");
  }

  async verifyEmailCode(): Promise<void> {
    throw new AuthFlowError("unavailable", "sign-in is not configured");
  }

  async signOut(): Promise<void> {}

  async signOutEverywhere(): Promise<void> {}

  subscribe(): () => void {
    return () => {};
  }
}

/** Supabase's error objects carry `status` and a machine `code`; a network
 *  failure is `AuthRetryableFetchError`. Read structurally so this stays a
 *  pure function and needs no handle on the lazily loaded module. */
function classify(error: unknown, step: "request" | "verify"): AuthFlowError {
  const e = (typeof error === "object" && error !== null ? error : {}) as {
    name?: unknown;
    status?: unknown;
    code?: unknown;
    message?: unknown;
  };
  const name = typeof e.name === "string" ? e.name : "";
  const status = typeof e.status === "number" ? e.status : 0;
  const code = typeof e.code === "string" ? e.code : "";
  const message = typeof e.message === "string" ? e.message : "sign-in failed";

  let reason: AuthFailureReason = "unknown";
  if (name === "AuthRetryableFetchError" || (status === 0 && error instanceof TypeError)) reason = "unreachable";
  else if (status === 429 || code.includes("rate_limit")) reason = "rate_limited";
  else if (code === "otp_disabled" || code === "signup_disabled" || code === "email_provider_disabled")
    reason = "unavailable";
  else if (step === "verify" && (code === "otp_expired" || code === "invalid_credentials" || status === 403))
    reason = "invalid_code";
  else if (step === "request" && (code === "email_address_invalid" || code === "validation_failed" || status === 400))
    reason = "invalid_email";
  return new AuthFlowError(reason, message);
}

function isNative(): boolean {
  try {
    return Capacitor.isNativePlatform();
  } catch {
    return false;
  }
}

export class SupabaseAuthSession implements AuthSession {
  readonly enabled = true;

  private client: SupabaseClient | null = null;
  private session: Session | null = null;
  private loading: Promise<void> | null = null;
  private readonly listeners = new Set<() => void>();
  /** Where supabase-js keeps the session: its own default key, named here
   *  so `hasSession()` can see a stored session before the library loads. */
  private readonly storageKey: string;

  constructor(
    private readonly url: string,
    private readonly publishableKey: string
  ) {
    this.storageKey = providerStorageKey(url);
  }

  private storedSession(): boolean {
    try {
      return window.localStorage.getItem(this.storageKey) !== null;
    } catch {
      return false;
    }
  }

  hasSession(): boolean {
    return this.session !== null || this.storedSession();
  }

  load(): Promise<void> {
    if (!this.loading) {
      this.loading = import("@supabase/supabase-js")
        .then(async ({ createClient }) => {
          const client = createClient(this.url, this.publishableKey, {
            auth: {
              persistSession: true,
              autoRefreshToken: true,
              flowType: "pkce",
              storageKey: this.storageKey,
              /* Only a web redirect (Google, phase 4) ever lands a session in
                 the URL. In the Capacitor WebView the app's own URL never
                 carries one, and parsing it there is pointless. */
              detectSessionInUrl: !isNative(),
            },
          });
          /* The callback only records: calling back into the client from
             inside it can deadlock supabase-js's own lock. Fires for sign-in,
             sign-out, token refresh and changes made in another tab. */
          client.auth.onAuthStateChange((_event, session) => {
            this.session = session;
            this.notify();
          });
          const { data } = await client.auth.getSession();
          this.client = client;
          this.session = data.session;
          this.notify();
        })
        .catch((err) => {
          /* A provider that will not load must not take the app down with it.
             Reset so a later call can try again. */
          this.loading = null;
          throw err;
        });
    }
    return this.loading;
  }

  user(): AuthUser | null {
    const user = this.session?.user;
    if (!user) return null;
    return { id: user.id, email: user.email ?? null };
  }

  async getToken(): Promise<string | null> {
    /* Waits for the provider (bounded) so the first requests of a page load
       are not sent anonymous a beat before the stored session is known.
       Null means "nobody is signed in"; a session that exists but cannot
       produce a token right now throws instead (see the port). */
    const unavailable = (why: string) => new AuthFlowError("unreachable", why);
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        this.load(),
        new Promise<void>((_, reject) => {
          timer = setTimeout(() => reject(new Error("auth load timed out")), LOAD_WAIT_MS);
        }),
      ]);
    } catch (err) {
      if (this.hasSession()) throw unavailable(err instanceof Error ? err.message : "auth did not load");
      return null;
    } finally {
      if (timer) clearTimeout(timer);
    }
    if (!this.client) {
      if (this.hasSession()) throw unavailable("auth did not load");
      return null;
    }
    /* Loaded. supabase-js removes a stored session it has found invalid, so
       one still stored but not in memory is one it could not recover on the
       network just now: not "signed out". */
    if (!this.session) {
      if (this.storedSession()) throw unavailable("stored session not recovered");
      return null;
    }
    /* getSession refreshes an expired access token before answering. */
    let token: string | null = null;
    try {
      const { data } = await this.client.auth.getSession();
      token = data.session?.access_token ?? null;
    } catch {
      token = null;
    }
    if (token) return token;
    if (this.hasSession()) throw unavailable("token refresh failed");
    return null;
  }

  private async ready(): Promise<SupabaseClient> {
    try {
      await this.load();
    } catch (err) {
      throw new AuthFlowError("unreachable", err instanceof Error ? err.message : "auth failed to load");
    }
    if (!this.client) throw new AuthFlowError("unreachable", "auth failed to load");
    return this.client;
  }

  async requestEmailCode(email: string): Promise<void> {
    const client = await this.ready();
    let error: unknown;
    try {
      ({ error } = await client.auth.signInWithOtp({ email, options: { shouldCreateUser: true } }));
    } catch (err) {
      error = err;
    }
    if (error) throw classify(error, "request");
  }

  async verifyEmailCode(email: string, code: string): Promise<void> {
    const client = await this.ready();
    let error: unknown;
    try {
      ({ error } = await client.auth.verifyOtp({ email, token: code, type: "email" }));
    } catch (err) {
      error = err;
    }
    if (error) throw classify(error, "verify");
  }

  async signOut(): Promise<void> {
    /* `local`: this device only. A failed network call still clears the
       stored session (supabase-js removes it before the request). The key is
       also removed by hand, so signing out works even when the library never
       loaded: a stored session nobody can use must not hold the app's
       requests hostage (see getToken). */
    if (this.client) await this.client.auth.signOut({ scope: "local" }).catch(() => undefined);
    try {
      window.localStorage.removeItem(this.storageKey);
    } catch {
      /* no storage: nothing stored */
    }
    this.session = null;
    this.notify();
  }

  async signOutEverywhere(): Promise<void> {
    /* Two steps, not `scope: "global"`: supabase-js removes the local session
       even when a global sign-out request fails, which would sign this device
       out while every other device stayed in. `others` revokes every other
       session and leaves this one untouched on failure, so a refusal or a
       dropped connection keeps the person signed in here with an error to
       read. Only then is this device signed out, the ordinary way. */
    const client = await this.ready();
    let error: unknown;
    try {
      ({ error } = await client.auth.signOut({ scope: "others" }));
    } catch (err) {
      error = err;
    }
    if (error) throw classify(error, "request");
    await this.signOut();
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}

export function buildAuthSession(): AuthSession {
  /* Read as two literal `process.env.NEXT_PUBLIC_*` expressions so Next
     inlines them at build time. */
  const url = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
  const key = (process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || "").trim();
  return url && key ? new SupabaseAuthSession(url, key) : new NullAuthSession();
}
