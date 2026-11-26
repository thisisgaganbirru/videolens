import type { Session, SupabaseClient } from "@supabase/supabase-js";
import type { AuthUser } from "@/domain/entities";
import { AuthFlowError, type AuthFailureReason } from "@/domain/errors";
import type { AuthRedirectBrowser, AuthRedirectResult, AuthSession } from "@/domain/ports";
import { readReturn } from "./authBrowser";
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

/** Set when Google sign-in starts here, cleared when its answer is read. A
 *  return without it is not acted on: a WebView reload re-reading the app's
 *  launch link, or a stale `?code=` in a bookmarked address, would otherwise
 *  be exchanged again and fail with a message nobody asked for. In
 *  localStorage (not memory) because the answer can arrive in a new page or
 *  a relaunched app; the Android backup rules already exclude it. */
const GOOGLE_PENDING_KEY = "videolens-google-signin-pending";
/** A consent page left open longer than this is treated as abandoned. */
const GOOGLE_PENDING_MAX_MS = 30 * 60 * 1000;
/** The settings read before leaving for Google is bounded like the load. */
const SETTINGS_WAIT_MS = 4000;

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

  async recover(): Promise<void> {}

  async requestEmailCode(): Promise<void> {
    throw new AuthFlowError("unavailable", "sign-in is not configured");
  }

  async verifyEmailCode(): Promise<void> {
    throw new AuthFlowError("unavailable", "sign-in is not configured");
  }

  async signInWithGoogle(): Promise<void> {
    throw new AuthFlowError("unavailable", "sign-in is not configured");
  }

  googlePending(): boolean {
    return false;
  }

  redirectResult(): AuthRedirectResult | null {
    return null;
  }

  dismissRedirectResult(): void {}

  async signOut(): Promise<void> {}

  async signOutEverywhere(): Promise<void> {}

  subscribe(): () => void {
    return () => {};
  }
}

/** Why a provider return carried an error, from its `error` and
 *  `error_code` parameters. `access_denied` is Google's "the person said no
 *  or closed the page". */
function returnFailure(error: string | null, errorCode: string | null, description: string | null): AuthFlowError {
  const message = description || error || "provider sign-in failed";
  if (error === "access_denied") return new AuthFlowError("cancelled", message);
  if (
    errorCode === "provider_disabled" ||
    errorCode === "signup_disabled" ||
    errorCode === "oauth_provider_not_supported" ||
    error === "unsupported_provider"
  )
    return new AuthFlowError("unavailable", message);
  if (errorCode === "over_request_rate_limit" || errorCode?.includes("rate_limit")) return new AuthFlowError("rate_limited", message);
  return new AuthFlowError("unknown", message);
}

/** Supabase's error objects carry `status` and a machine `code`; a network
 *  failure is `AuthRetryableFetchError`. Read structurally so this stays a
 *  pure function and needs no handle on the lazily loaded module. */
function classify(error: unknown, step: "request" | "verify" | "google"): AuthFlowError {
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
  else if (
    code === "otp_disabled" ||
    code === "signup_disabled" ||
    code === "email_provider_disabled" ||
    code === "provider_disabled"
  )
    reason = "unavailable";
  else if (step === "verify" && (code === "otp_expired" || code === "invalid_credentials" || status === 403))
    reason = "invalid_code";
  else if (step === "request" && (code === "email_address_invalid" || code === "validation_failed" || status === 400))
    reason = "invalid_email";
  return new AuthFlowError(reason, message);
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

  /** Google sign-in (phase 4): on its way to the consent page. */
  private pending = false;
  /** The last provider return's outcome, until a screen dismisses it. */
  private result: AuthRedirectResult | null = null;
  private resultSeq = 0;
  private watchingReturns = false;

  constructor(
    private readonly url: string,
    private readonly publishableKey: string,
    private readonly browser: AuthRedirectBrowser
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

  private watchingOtherTabs = false;

  /* 2026-11-20: another tab signing out removes the stored session, and this
     tab must stop treating its in-memory copy as signed in at once, whether
     or not supabase-js relays the change itself (it does not when the other
     tab never loaded the library and removed the key by hand). The `storage`
     event fires only in the *other* tabs of this origin. Only a removal is
     acted on: a sign-in or a refreshed token in another tab is the
     library's own business. */
  private watchOtherTabs(): void {
    if (this.watchingOtherTabs || typeof window === "undefined") return;
    this.watchingOtherTabs = true;
    try {
      window.addEventListener("storage", (event) => {
        /* `key` is null when the other tab cleared all of localStorage. */
        if (event.key !== null && event.key !== this.storageKey) return;
        if (this.storedSession() || this.session === null) return;
        this.session = null;
        this.notify();
      });
    } catch {
      /* no window events: the library's own relay is all there is */
    }
  }

  load(): Promise<void> {
    this.watchOtherTabs();
    if (!this.loading) {
      this.loading = import("@supabase/supabase-js")
        .then(async ({ createClient }) => {
          const client = createClient(this.url, this.publishableKey, {
            auth: {
              persistSession: true,
              autoRefreshToken: true,
              flowType: "pkce",
              storageKey: this.storageKey,
              /* Off everywhere (2026-11-22, phase 4). The one redirect that
                 lands here, Google's, is read by `finishReturn` below on the
                 web and in the app alike: it also reads a refusal (which the
                 library leaves in the address bar and reports nowhere a
                 screen can see) and strips the parameters through a history
                 entry Next keeps in sync. */
              detectSessionInUrl: false,
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
          this.watchReturns(client);
          /* A Google answer that is already here (the web return page, or the
             link that launched the app) is read before `load` settles, so the
             panel goes from "Loading…" straight to signed in. */
          const initial = await this.browser.takeInitialReturn().catch(() => null);
          if (initial) await this.finishReturn(client, initial);
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

  async recover(): Promise<void> {
    /* A provider that never loaded is loaded again (`load` resets itself on
       failure); a loaded one is asked for the stored session again, which
       retries the refresh that failed. */
    try {
      if (!this.client) {
        await this.load();
      } else {
        const { data } = await this.client.auth.getSession();
        this.session = data.session;
      }
    } catch {
      /* still unreachable: the stored session stays for the next try */
    }
    this.notify();
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

  /* ------------------------------------------------- Google (auth phase 4) */

  async signInWithGoogle(): Promise<void> {
    const client = await this.ready();
    await this.checkGoogleEnabled();
    let url: string | null = null;
    let error: unknown;
    try {
      /* `skipBrowserRedirect`: the library only builds the address (and
         stores the PKCE verifier); `browser.open` decides where it opens. */
      const response = await client.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: await this.browser.returnUrl(),
          skipBrowserRedirect: true,
          /* Always offer the account chooser, so a shared phone or browser
             does not sign in as whoever used Google there last. */
          queryParams: { prompt: "select_account" },
        },
      });
      error = response.error;
      url = response.data?.url ?? null;
    } catch (err) {
      error = err;
    }
    if (error || !url) throw classify(error ?? new Error("no consent address"), "google");
    this.setPendingMarker(true);
    this.pending = true;
    this.notify();
    try {
      await this.browser.open(url);
    } catch (err) {
      this.setPendingMarker(false);
      this.pending = false;
      this.notify();
      throw new AuthFlowError("unknown", err instanceof Error ? err.message : "could not open the consent page");
    }
  }

  googlePending(): boolean {
    return this.pending;
  }

  redirectResult(): AuthRedirectResult | null {
    return this.result;
  }

  dismissRedirectResult(id: number): void {
    if (this.result?.id !== id) return;
    this.result = null;
    this.notify();
  }

  /** Asks the project whether Google is switched on before leaving for it:
   *  with the provider off, Supabase answers the consent address with a bare
   *  JSON error page, a dead end with no way back into the app. A settings
   *  read that answers oddly lets the attempt go ahead (the return then
   *  carries any refusal); one that cannot be made at all means the sign-in
   *  service is out of reach, as for an emailed code. */
  private async checkGoogleEnabled(): Promise<void> {
    const controller = typeof AbortController === "undefined" ? null : new AbortController();
    const timer = controller ? setTimeout(() => controller.abort(), SETTINGS_WAIT_MS) : undefined;
    let response: Response;
    try {
      response = await fetch(`${this.url.replace(/\/+$/, "")}/auth/v1/settings`, {
        headers: { apikey: this.publishableKey },
        signal: controller?.signal,
      });
    } catch (err) {
      throw new AuthFlowError("unreachable", err instanceof Error ? err.message : "settings unreachable");
    } finally {
      if (timer) clearTimeout(timer);
    }
    if (!response.ok) return;
    let google: unknown;
    try {
      const body = (await response.json()) as { external?: Record<string, unknown> };
      google = body.external?.google;
    } catch {
      return;
    }
    if (google === false) throw new AuthFlowError("unavailable", "the Google provider is not enabled");
  }

  private setPendingMarker(on: boolean): void {
    try {
      if (on) window.localStorage.setItem(GOOGLE_PENDING_KEY, String(Date.now()));
      else window.localStorage.removeItem(GOOGLE_PENDING_KEY);
    } catch {
      /* no storage: the PKCE verifier cannot be kept either, and the
         exchange will say so */
    }
  }

  /** Reads and clears the marker. True when a sign-in started here recently. */
  private takePendingMarker(): boolean {
    let raw: string | null = null;
    try {
      raw = window.localStorage.getItem(GOOGLE_PENDING_KEY);
      window.localStorage.removeItem(GOOGLE_PENDING_KEY);
    } catch {
      return false;
    }
    const started = raw === null ? NaN : Number(raw);
    return Number.isFinite(started) && Date.now() - started <= GOOGLE_PENDING_MAX_MS;
  }

  private publish(outcome: { ok: true } | { ok: false; error: AuthFlowError }): void {
    this.resultSeq += 1;
    this.result = { id: this.resultSeq, ...outcome };
    this.notify();
  }

  /** The app's deep links, and the consent page left without an answer.
   *  Registered once, when the client exists. */
  private watchReturns(client: SupabaseClient): void {
    if (this.watchingReturns) return;
    this.watchingReturns = true;
    this.browser.watch({
      onReturn: (url) => {
        void this.finishReturn(client, url);
      },
      onClosed: () => {
        if (!this.pending) return;
        this.pending = false;
        this.notify();
      },
    });
  }

  /** One provider return: the code is exchanged for a session (PKCE; the
   *  verifier is in this origin's storage), or the error is kept for the
   *  panel. Never rejects. */
  private async finishReturn(client: SupabaseClient, raw: string): Promise<void> {
    void this.browser.close();
    /* Synchronous, before any await: a cold start can hear the same link
       twice (launch URL and `appUrlOpen`), and only the first is acted on. */
    if (!this.takePendingMarker()) return;
    this.pending = false;
    const { code, error, errorCode, description } = readReturn(raw);
    if (error || errorCode || !code) {
      this.publish({ ok: false, error: returnFailure(error, errorCode, description) });
      return;
    }
    let failure: unknown;
    try {
      ({ error: failure } = await client.auth.exchangeCodeForSession(code));
    } catch (err) {
      failure = err;
    }
    if (failure) {
      this.publish({ ok: false, error: classify(failure, "google") });
      return;
    }
    /* `onAuthStateChange` has already recorded the session. */
    this.publish({ ok: true });
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

export function buildAuthSession(browser: AuthRedirectBrowser): AuthSession {
  /* Read as two literal `process.env.NEXT_PUBLIC_*` expressions so Next
     inlines them at build time. */
  const url = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
  const key = (process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || "").trim();
  return url && key ? new SupabaseAuthSession(url, key, browser) : new NullAuthSession();
}
