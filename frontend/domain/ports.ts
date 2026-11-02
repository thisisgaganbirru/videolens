/* Interfaces the application layer (hooks) depends on. Infrastructure
   adapters implement these; components never import an adapter directly -
   they go through a hook, which goes through the shared container. */

import type {
  CapabilityReport,
  FreeRunsStatus,
  HistoryPatch,
  HistoryRecord,
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

/** `GET /api/free-runs`: this device's free-run allowance. Read-only on the
 *  server; it issues a fresh token when the stored one is missing or invalid,
 *  and the adapter keeps the `DeviceTokenStore` in step with whatever comes
 *  back. */
export interface FreeRunsGateway {
  fetchStatus(): Promise<FreeRunsStatus>;
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
  releaseUrl: string;
};

export interface UpdateChecker {
  checkForUpdate(): Promise<UpdateInfo | null>;
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
 * Keeps the OS system bars (status bar + gesture/navigation bar) legible over
 * the page. The app is edge-to-edge on native, so the WebView paints under the
 * bars and their icon colour has to follow the app's theme, not the OS's.
 * A no-op wherever there are no native bars to style (browser, PWA).
 */
export interface SystemBarsStyler {
  matchTheme(theme: PaintedTheme): Promise<void>;
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
 * opens the system share sheet with the document text: a blob download goes
 * nowhere in a Capacitor WebView, and writing a real file needs
 * @capacitor/filesystem, which is not installed.
 */
export interface DocumentExporter {
  /** A share sheet exists here (Capacitor, or the Web Share API). */
  canShare(): boolean;
  /** Save resolves to the share sheet rather than a file download. */
  savesViaShareSheet(): boolean;
  share(doc: MarkdownDocument): Promise<void>;
  save(doc: MarkdownDocument): Promise<void>;
}
