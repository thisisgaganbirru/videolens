/* Interfaces the application layer (hooks) depends on. Infrastructure
   adapters implement these; components never import an adapter directly -
   they go through a hook, which goes through the shared container. */

import type {
  AccountResponse,
  BillingInterval,
  BillingStatus,
  ApiKeyCreated,
  ApiKeyListResponse,
  AuthUser,
  CapabilityReport,
  FreeRunsStatus,
  HistoryPatch,
  HistoryRecord,
  MediaLimitsTable,
  MediaSource,
  RunCreateResponse,
  RunListResponse,
  RunStatusResponse,
} from "./entities";

export interface RunsGateway {
  createRun(source: MediaSource): Promise<RunCreateResponse>;
  getRun(runId: string): Promise<RunStatusResponse>;
  listRuns(): Promise<RunListResponse>;
}

/**
 * This browser's run History — the only copy that outlives the server's
 * one-hour hold on a run. Capped: once more than `HISTORY_LIMIT` runs are
 * stored, the oldest (by `created_at`) is dropped.
 *
 * Every method rejects with `StorageUnavailableError` when the browser offers
 * no usable storage; callers that only *write* history swallow that, because
 * History must never be the reason an analysis fails.
 */
export interface HistoryStore {
  /** Every stored run, newest first. */
  list(): Promise<HistoryRecord[]>;
  get(runId: string): Promise<HistoryRecord | null>;
  /** Merge into the stored record (or create it), then enforce the cap. */
  upsert(patch: HistoryPatch): Promise<void>;
  /** Called after any write, from this tab or another. Returns unsubscribe. */
  subscribe(listener: () => void): () => void;
}

/** Reads the deployment's own capability report. Separate from `RunsGateway`
 *  because it carries no caller identity at all: no `X-Client-ID`, no BYOK
 *  key, nothing that scopes the answer to one user. It describes the server,
 *  not the caller's runs. */
export interface CapabilitiesGateway {
  fetchReport(): Promise<CapabilityReport>;
}

/** The run this browser tab is watching, kept for the tab's lifetime so a
 *  reload mid-run picks the same run back up (refinement 6, RUN-06 web).
 *  Per tab on purpose: two tabs may each be watching their own run. Never
 *  throws; unreadable storage reads as "no run". */
export interface ActiveRunStore {
  get(): string | null;
  set(runId: string): void;
  clear(): void;
}

export interface ApiKeyStore {
  get(): string;
  set(apiKey: string): void;
  /** Notifies after the stored key changes — from this tab (the API key page
   *  saving or removing it) or another. The free-run banner listens, so it
   *  disappears the moment a key is saved. Returns unsubscribe. */
  subscribe(listener: () => void): () => void;
}

/** The free-run device token, kept on this device. A random value the server
 *  issued; not a secret and not tied to a person — it only counts this
 *  device's free runs per UTC day. `get()` returns "" when there is none, or
 *  when the browser refuses storage. */
export interface DeviceTokenStore {
  get(): string;
  set(token: string): void;
}

/** `GET /api/free-runs`: the free-run allowance this caller is counted
 *  against (this device's, or the signed-in account's when the request
 *  carries a bearer; the shared `ApiClient` adds it). Read-only on the
 *  server; it issues a fresh token when the stored one is missing or invalid,
 *  and the adapter keeps the `DeviceTokenStore` in step with whatever comes
 *  back. */
export interface FreeRunsGateway {
  fetchStatus(): Promise<FreeRunsStatus>;
}

/** `GET /api/limits`: the upload limits per tier. Public, no caller
 *  identity. Rejects when the endpoint is missing or unreadable; the hook
 *  falls back to the standard limits then. */
export interface LimitsGateway {
  fetchLimits(): Promise<MediaLimitsTable>;
}

/** `/api/billing*` for the signed-in person (2026-11-13). Both redirects are
 *  Stripe-hosted pages; these only ask the server for their address.
 *  Reject with `ApiError` (`code` `already_subscribed` on checkout,
 *  `no_billing_account` on the portal) or `NetworkError`. */
export interface BillingGateway {
  fetchBilling(): Promise<BillingStatus>;
  /** `POST /api/billing/checkout`: the hosted Checkout page's URL. */
  startCheckout(interval: BillingInterval): Promise<string>;
  /** `POST /api/billing/portal`: the hosted Customer Portal's URL. */
  openPortal(): Promise<string>;
}

export type VersionLogEntry = {
  name: string;
  tag: string;
  publishedAt: string;
  url: string;
};

export interface VersionLogGateway {
  fetchEntries(): Promise<VersionLogEntry[]>;
}

export type UpdateInfo = {
  versionName: string;
  /** The newer build's Android `versionCode`. What a dismissal remembers, so
   *  dismissing one build never hides a later one (refinement 9). */
  versionCode: number;
  releaseUrl: string;
};

export interface UpdateChecker {
  checkForUpdate(): Promise<UpdateInfo | null>;
}

/**
 * The update banner's "not now" (refinement 9): the newest build the user
 * dismissed. Device-local and best-effort — unreadable storage reads as
 * "nothing dismissed", so the banner shows rather than silently never showing.
 */
export interface UpdateDismissalStore {
  /** The dismissed build's `versionCode`, or null. */
  dismissedCode(): number | null;
  dismiss(versionCode: number): void;
}

/**
 * A URL handed to the app from outside it — an Android share intent, or the
 * PWA manifest's `share_target` query params.
 *
 * `take()` consumes: the same share is never returned twice, so a remount or a
 * back navigation cannot replay a link the user already dealt with.
 */
export interface SharedUrlSource {
  /** The pending shared URL, or `null` if there is none. Consuming. */
  take(): string | null;
  /** Whether a share is waiting to be taken, without taking it. Lets the
   *  first-run Welcome step aside for a launch that carried a link. */
  pending(): boolean;
  /** Notifies when a share lands while the app is already open. Returns an
   *  unsubscribe function. */
  subscribe(listener: () => void): () => void;
}

/** Which theme the page is painting. Mirrors `Theme` in `components/theme.ts`;
 *  restated here so `domain/` stays free of presentation imports. */
export type PaintedTheme = "light" | "dark";

/**
 * Keeps the OS system bars (status bar + gesture/navigation bar) legible. Where
 * the WebView paints under the bars (Android WebView 140+) the icon colour
 * follows the app's theme; on older WebViews the bars show the OS-themed
 * window background, so it follows the OS theme instead (refinement 2, #2).
 * A no-op wherever there are no native bars to style (browser, PWA).
 */
export interface SystemBarsStyler {
  matchTheme(theme: PaintedTheme): Promise<void>;
  /** True when the bars' background follows the OS theme, not the page: the
   *  caller must re-apply when the OS theme changes. */
  followsSystemTheme(): boolean;
}

/** The theme the user chose, as the More sheet shows it: "system" follows the
 *  device. Mirrors `ThemePreference` in `components/theme.ts`. */
export type ThemeChoice = PaintedTheme | "system";

/**
 * Tells the native shell which theme the user chose, so the next launch can
 * apply it before the first frame (launch screen, window background, system
 * bars) instead of following the OS night mode — refinement 5, THM-01b.
 * A no-op (resolves false) wherever there is no native shell.
 */
export interface NativeThemeMirror {
  /** Resolves true when the native night mode actually changed. */
  setPreference(choice: ThemeChoice): Promise<boolean>;
  /**
   * The OS's own night state as the native shell reads it, or null where
   * there is no native shell (or it cannot say). Refinement 7, THM-01b-6: on
   * Android the WebView's `prefers-color-scheme` can stay stale after the app
   * lifts a forced night mode, so under "system" this is the value to paint.
   */
  systemNight(): Promise<boolean | null>;
  /** Called with the new OS night state whenever the native shell sees it
   *  change. Returns an unsubscribe. A no-op where there is no native shell. */
  onSystemNightChange(listener: (dark: boolean) => void): () => void;
}

/**
 * What the installed app's first-run screens remember (Phase 5d): whether the
 * Welcome screen has been dismissed for good, and whether this session has
 * already shown the Welcome or the cold-start splash. Every read and write
 * survives storage that throws or is missing — the answer then errs towards
 * not showing a screen again.
 */
export interface FirstRunStore {
  /** True once Welcome was dismissed on this device, or shown this session. */
  welcomeSeen(): boolean;
  /** Welcome was dismissed with one of its own buttons: never show it again. */
  markWelcomeSeen(): void;
  /** Welcome was put on screen: do not show it again this session. */
  markWelcomeShownThisSession(): void;
  /** The cold-start splash has played this session. */
  markSplashShown(): void;
}

/**
 * The installed Android app's native shell (refinement 1, #4): the hardware
 * back button and leaving the app. Everywhere else (browser, PWA, iOS) it
 * reports not-native and its listener never fires.
 */
export interface NativeShell {
  isNative(): boolean;
  /** Takes over the hardware back button. `canGoBack` is the WebView's own
   *  history answer. Returns the unsubscribe. */
  onBackButton(handler: (canGoBack: boolean) => void): () => void;
  /** The app came back to the foreground (refinement 9). Off the native
   *  shell nothing is registered; `visibilitychange` covers browsers.
   *  Returns the unsubscribe. */
  onResume(handler: () => void): () => void;
  exitApp(): void;
}

/** One finished analysis as a single Markdown document. */
export type MarkdownDocument = {
  /** File name without the extension. */
  filename: string;
  title: string;
  text: string;
};

/**
 * Getting a result out of the app (refinement 1, #12/#13). Share and save both
 * hand over the whole report, never one tab. On the Android shell "save"
 * writes a real `<filename>.md` to the app cache and opens the system share
 * sheet with that file (refinement 2, #1): a blob download goes nowhere in a
 * Capacitor WebView. In a browser it is a plain download.
 */
export interface DocumentExporter {
  /** A share sheet exists here (Capacitor, or the Web Share API). */
  canShare(): boolean;
  /** Save resolves to the share sheet rather than a file download. */
  savesViaShareSheet(): boolean;
  share(doc: MarkdownDocument): Promise<void>;
  save(doc: MarkdownDocument): Promise<void>;
}

/**
 * Who is signed in, behind the identity provider (auth phase 2).
 *
 * Optional by design: with no provider configured the container builds a
 * session whose `enabled` is false, every request goes out anonymous, and the
 * Account tab is not offered. Sign-in is an emailed one-time code, the one
 * method that works the same in a browser tab and inside the Capacitor
 * WebView (no redirect, no deep link). Google sign-in is phase 4 and is not on
 * this port yet.
 *
 * Failures of `requestEmailCode` and `verifyEmailCode` reject with
 * `AuthFlowError` (domain/errors.ts), whose `reason` the hook words.
 */
export interface AuthSession {
  /** False when the deployment has no identity provider configured. */
  readonly enabled: boolean;
  /** Loads the provider and restores a stored session. Idempotent. */
  load(): Promise<void>;
  /** The signed-in person, or null. Synchronous: reads the loaded state. */
  user(): AuthUser | null;
  /** True when a session exists, in memory or stored on this device, even
   *  before the provider has loaded. Synchronous; no network. */
  hasSession(): boolean;
  /** A current access token for the API, refreshed when needed. Null only
   *  when nobody is signed in (or sign-in is unconfigured). When a session
   *  exists but no token can be had right now (the provider is slow to load,
   *  a refresh failed on the network) it **throws**: sending that request
   *  anonymously would reach runs owned by the person as someone else. */
  getToken(): Promise<string | null>;
  /** Emails a one-time code. Creates the account on first use. */
  requestEmailCode(email: string): Promise<void>;
  /** Exchanges the emailed code for a session. */
  verifyEmailCode(email: string, code: string): Promise<void>;
  /** Signs out on this device only. Never rejects; the stored session is
   *  cleared even when the provider cannot be reached. */
  signOut(): Promise<void>;
  /** Ends every session of this person (other devices and this one). Rejects
   *  with `AuthFlowError` when the provider refused or could not be reached,
   *  and then this device **stays signed in**. Other devices keep a valid
   *  access token until it expires (the API verifies tokens by JWKS only),
   *  and VideoLens API keys are not touched. */
  signOutEverywhere(): Promise<void>;
  /** Called whenever the session changes (sign-in, sign-out, a token
   *  refresh, another tab). Returns unsubscribe. */
  subscribe(listener: () => void): () => void;
}

/** Whether *this server* verifies sign-in tokens: its `auth` capability.
 *  `unknown` until the capability report arrives. The bearer goes out only
 *  on `ok`, because the backend reads a bearer *instead of* `X-Client-ID`: a
 *  server without a matching verifier would answer 401/503 to every caller
 *  route (auth phase 2). Fed by the capabilities adapter, read by the API
 *  client. */
export type ServerAuthState = "unknown" | "ok" | "off";

export interface ServerAuthStatus {
  current(): ServerAuthState;
  report(state: Exclude<ServerAuthState, "unknown">): void;
  /** Resolves with the state once known, or with `unknown` after `maxMs`. */
  settled(maxMs: number): Promise<ServerAuthState>;
}

/** Which identity the app's requests are going out as, so a History record
 *  can remember who owns its run: `user:<id>` when the bearer is sent,
 *  `anonymous` otherwise; null before the first request. */
export interface CallerIdentity {
  lastOwner(): string | null;
}

/** `/api/me` and `/api/keys`, sent as the signed-in person. */
export interface AccountGateway {
  fetchAccount(): Promise<AccountResponse>;
  listKeys(): Promise<ApiKeyListResponse>;
  createKey(name: string): Promise<ApiKeyCreated>;
  revokeKey(keyId: string): Promise<void>;
  /** `DELETE /api/me` (auth phase 3): the account, its workspace, API keys
   *  and any runs the server still holds for it. Resolves on 204; rejects
   *  with `ApiError` (401, 403, 503, anything unexpected) or `NetworkError`. */
  deleteAccount(): Promise<void>;
}
