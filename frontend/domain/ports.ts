/* Interfaces the application layer (hooks) depends on. Infrastructure
   adapters implement these; components never import an adapter directly -
   they go through a hook, which goes through the shared container. */

import type {
  AccountDeletionOutcome,
  AccountResponse,
  SavedRunDetail,
  SavedRunPage,
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
import type { AuthFlowError } from "./errors";

/** A response plus the identity it was asked as (`user:<id>`, `anonymous`,
 *  or null when a token came without a known user). Read from the request
 *  itself, so a second request in flight cannot change whose it is. */
export type AsOwner<T> = T & { owner: string | null };

export interface RunsGateway {
  /** `signal` aborts the upload (cancel, or the screen going away). */
  createRun(source: MediaSource, signal?: AbortSignal): Promise<AsOwner<RunCreateResponse>>;
  getRun(runId: string): Promise<RunStatusResponse>;
  listRuns(): Promise<AsOwner<RunListResponse>>;
}

/**
 * This browser's run History — the only copy that outlives the server's
 * one-hour hold on a run. Capped per viewer (2026-11-21): once more than
 * `HISTORY_LIMIT` runs that the written row's owner can see
 * (`isVisibleOwner`) are stored, the oldest of those (by `created_at`) is
 * dropped. A row hidden from that owner (another account's, kept while it is
 * signed out) is never dropped by someone else's run.
 *
 * The read and write methods reject with `StorageUnavailableError` when the
 * browser offers no usable storage; callers that only *write* history swallow
 * that, because History must never be the reason an analysis fails. The two
 * removals resolve instead: an empty store has nothing to remove.
 */
export interface HistoryStore {
  /** Every stored run, newest first. */
  list(): Promise<HistoryRecord[]>;
  get(runId: string): Promise<HistoryRecord | null>;
  /** Merge into the stored record (or create it), then enforce the cap. */
  upsert(patch: HistoryPatch): Promise<void>;
  /** Merge into the stored record only when it is still there; never
   *  creates one. Resolves whether a row was updated. The check and the
   *  write share one transaction, so a row removed meanwhile (from any tab)
   *  stays removed. `when`, if given, is asked about the stored row inside
   *  that transaction; false writes nothing and resolves false (2026-11-21:
   *  a row hidden from whoever is signed in now is never updated). */
  update(patch: HistoryPatch, when?: (existing: HistoryRecord) => boolean): Promise<boolean>;
  /** Drop one stored run from this device. Resolves (a no-op) when storage
   *  is unavailable: there is nothing kept here to remove. */
  remove(runId: string): Promise<void>;
  /** Drop every stored run whose `owner` passes `match`; resolves with how
   *  many went. Rows with no owner are never matched. Resolves 0 when storage
   *  is unavailable, like `remove`. Used only when an account is deleted from
   *  this browser (2026-11-21); a plain sign-out removes nothing. */
  removeOwnedBy(match: (owner: string) => boolean): Promise<number>;
  /** Called after any write, from this tab or another. Returns unsubscribe. */
  subscribe(listener: () => void): () => void;
}

/** Reads the deployment's own capability report. Separate from `RunsGateway`
 *  because it carries no caller identity at all: no `X-Client-ID`, no BYOK
 *  key, nothing that scopes the answer to one user. It describes the server,
 *  not the caller's runs. */
export interface CapabilitiesGateway {
  /** One read at a time: a call while a read is in flight shares it. */
  fetchReport(): Promise<CapabilityReport>;
  /** Hears every report that arrives, whoever asked for it (2026-11-21: the
   *  transport re-reads while sign-in is unconfirmed, and the screens that
   *  show capabilities must see the newer answer). Returns unsubscribe. */
  subscribe(listener: (report: CapabilityReport) => void): () => void;
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
  /** Tries again to restore a session that is stored on this device but
   *  could not be recovered (the provider would not load, or its refresh
   *  failed on the network). Notifies either way; never rejects. A no-op
   *  where sign-in is unconfigured. */
  recover(): Promise<void>;
  /** Emails a one-time code. Creates the account on first use. */
  requestEmailCode(email: string): Promise<void>;
  /** Exchanges the emailed code for a session. */
  verifyEmailCode(email: string, code: string): Promise<void>;
  /** Starts Google sign-in (auth phase 4). On the web this tab navigates to
   *  the consent page; in the installed app the system browser opens it
   *  (Google refuses embedded WebViews). Resolves once the page is on its
   *  way; the answer comes back later as `redirectResult()`. Rejects with
   *  `AuthFlowError` when it cannot start (`unavailable`: the provider is not
   *  enabled on this project; `unreachable`). */
  signInWithGoogle(): Promise<void>;
  /** True from `signInWithGoogle()` until its answer arrives or the person
   *  leaves the consent page without one (closes the app's browser, or comes
   *  back to this tab with Back). Synchronous. */
  googlePending(): boolean;
  /** How the last provider redirect ended (signed in, cancelled, failed),
   *  until dismissed; null when there is none. On the web it arrives with
   *  the page load that brings the person back, read during `load()`; in the
   *  app, with the deep link. Listeners are notified when one arrives. */
  redirectResult(): AuthRedirectResult | null;
  /** Forgets the redirect result with this id (shown, or acted on). */
  dismissRedirectResult(id: number): void;
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

/** How a provider redirect (Google sign-in) came back. `id` tells one answer
 *  from the next, so a screen acts on each once. */
export type AuthRedirectResult = { id: number; ok: true } | { id: number; ok: false; error: AuthFlowError };

/**
 * Where a provider's consent page is shown and how its answer comes back
 * (Google sign-in, auth phase 4). The identity adapter drives it; it knows
 * nothing about the provider.
 *
 * - Web: this tab navigates to the page, and the provider sends it back to
 *   `/app?view=account` with `?code=` (or `?error=`).
 * - Installed app: the system browser (a Custom Tab), and the provider sends
 *   it to `<applicationId>://auth/callback` (`ai.videolens.app` in
 *   production, `ai.videolens.app.dev` for the dev APK), which Android hands
 *   back to that app alone (`AndroidManifest.xml`).
 */
export interface AuthRedirectBrowser {
  /** The address the provider must send the person back to. Must be in the
   *  provider project's redirect allowlist. Async: the installed app reads
   *  its own application id for the scheme. */
  returnUrl(): Promise<string>;
  /** Shows the provider's page. Web: navigates this tab away. */
  open(url: string): Promise<void>;
  /** Closes the app's browser if it is still open. Web: nothing. */
  close(): Promise<void>;
  /** A return already waiting when this page started: the current address
   *  on the web (whose return parameters are then removed from the address
   *  bar), the link that launched the app in the app. Null otherwise. */
  takeInitialReturn(): Promise<string | null>;
  /** Returns that arrive while the page runs (the app's deep link), and the
   *  person leaving the consent page without one (the app's browser closed;
   *  on the web, this tab restored from the back/forward cache). Returns the
   *  unsubscribe. */
  watch(handlers: { onReturn(url: string): void; onClosed(): void }): () => void;
}

/** Whether *this server* verifies sign-in tokens: its `auth` capability.
 *  `unknown` until the capability report arrives. The bearer goes out only
 *  on `ok`, because the backend reads a bearer *instead of* `X-Client-ID`: a
 *  server without a matching verifier would answer 401/503 to every caller
 *  route (auth phase 2). Fed by the capabilities adapter, read by the API
 *  client.
 *
 *  `degraded` (2026-11-21): the server verifies tokens but could not reach
 *  the sign-in keys just now. Not `off`: a person signed in must not be sent
 *  anonymous because of a blip, so the client treats it like `unknown`
 *  (waits, then fails as "sign-in could not be confirmed") and asks again. */
export type ServerAuthState = "unknown" | "ok" | "off" | "degraded";

export interface ServerAuthStatus {
  current(): ServerAuthState;
  report(state: Exclude<ServerAuthState, "unknown">): void;
  /** Resolves as soon as the state is decisive (`ok` or `off`), or after
   *  `maxMs` with whatever it is then (`unknown` or `degraded`). While it
   *  waits it asks for fresh reports (see `requestReport`). */
  settled(maxMs: number): Promise<ServerAuthState>;
  /** A caller needs a decisive state and does not have one: ask the
   *  capabilities source to read again. Deduplicated (one read in flight)
   *  and spaced (a minimum interval), so a failing backend is not hammered.
   *  A no-op until a reader is registered. */
  requestReport(): void;
  /** Registers the one reader `requestReport` runs (the composition root
   *  wires the capabilities adapter). Its failure is swallowed. */
  setReader(reader: () => Promise<unknown>): void;
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
  /** `DELETE /api/me`. Since 2026-11-14 it starts a 30-day hold: 200
   *  `{status: "pending_deletion", purge_at}`, resolved as `purgeAt`. An
   *  older backend's 204 (removed at once) resolves with `purgeAt: null`.
   *  Rejects with `ApiError` (401, 403, 410, 503, anything unexpected) or
   *  `NetworkError`. */
  deleteAccount(): Promise<AccountDeletionOutcome>;
  /** `POST /api/me/restore`: lifts the hold. True when it was held and now
   *  is not; false when it was not held. Rejects with `ApiError` (410
   *  `restore_window_closed` once `purge_at` has passed) or `NetworkError`. */
  restoreAccount(): Promise<boolean>;
}

/** Paid saved history (2026-11-14): the account's saved runs on the server.
 *  Signed-in sessions only (401 anonymous, 403 an API key, 410 a held
 *  account). An older backend answers 404 to all of it. */
export interface SavedHistoryGateway {
  /** `GET /api/history?limit=&cursor=`, newest first. */
  list(limit: number, cursor: string | null): Promise<SavedRunPage>;
  /** `GET /api/history/{run_id}`; `ApiError` 404 when it is not saved. */
  get(runId: string): Promise<SavedRunDetail>;
  /** `DELETE /api/history/{run_id}`; 204. */
  remove(runId: string): Promise<void>;
  /** `DELETE /api/history`; how many were removed. */
  removeAll(): Promise<number>;
}

/** A held account was refused (410 `account_pending_deletion`, any route),
 *  as the API client heard it: which identity the request went out as
 *  (`user:<id>`) and when the account is removed for good. */
export interface AccountHoldNotice {
  owner: string | null;
  purgeAt: string | null;
}

/** Every 410 `account_pending_deletion` the API client receives, whichever
 *  gateway made the request. Returns unsubscribe. */
export interface AccountHoldSource {
  subscribe(listener: (notice: AccountHoldNotice) => void): () => void;
}
