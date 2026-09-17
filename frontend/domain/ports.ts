/* Interfaces the application layer (hooks) depends on. Infrastructure
   adapters implement these; components never import an adapter directly -
   they go through a hook, which goes through the shared container. */

import type {
  AccountResponse,
  ApiKeyCreated,
  ApiKeyListResponse,
  AuthUser,
  CapabilityReport,
  LibraryQuery,
  LibraryResponse,
  MediaSource,
  Plan,
  RunCreateResponse,
  RunListResponse,
  RunStatusResponse,
} from "./entities";

export interface RunsGateway {
  createRun(source: MediaSource): Promise<RunCreateResponse>;
  getRun(runId: string): Promise<RunStatusResponse>;
  listRuns(): Promise<RunListResponse>;
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
  /** Notifies when a share lands while the app is already open. Returns an
   *  unsubscribe function. */
  subscribe(listener: () => void): () => void;
}

/**
 * The signed-in session, if the deployment has an identity provider.
 *
 * `enabled` is false on a deployment with no provider configured; every
 * other method is then a harmless no-op (`getToken` resolves `null`, so
 * every request goes out anonymous exactly as it did before accounts
 * existed). Nothing outside the adapter knows which provider it is.
 */
export interface AuthSession {
  readonly enabled: boolean;
  /** Loads the provider once and resolves when the session state is known.
   *  Idempotent; safe to call from every place that needs the answer. */
  load(): Promise<void>;
  /** The signed-in user, or `null` when nobody is (or nothing has loaded). */
  user(): AuthUser | null;
  /** A fresh bearer token for the API, or `null` when signed out. */
  getToken(): Promise<string | null>;
  signIn(): Promise<void>;
  signOut(): Promise<void>;
  /** Notifies when the user signs in or out. Returns an unsubscribe. */
  subscribe(listener: () => void): () => void;
}

/** The account panel's half of the API: who am I, what does my plan allow,
 *  and the money-shaped calls that change it. Every method sends the same
 *  identity headers `RunsGateway` does, so the answer is about *this* caller. */
export interface AccountGateway {
  fetchAccount(): Promise<AccountResponse>;
  listKeys(): Promise<ApiKeyListResponse>;
  createKey(name: string): Promise<ApiKeyCreated>;
  revokeKey(keyId: string): Promise<void>;
  /** Resolves with the provider's checkout URL; the caller navigates. */
  startCheckout(plan: Plan): Promise<string>;
  /** Resolves with the provider's billing-portal URL; the caller navigates. */
  openBillingPortal(): Promise<string>;
}

export interface LibraryGateway {
  search(params: LibraryQuery): Promise<LibraryResponse>;
}
