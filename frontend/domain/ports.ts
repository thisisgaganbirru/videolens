/* Interfaces the application layer (hooks) depends on. Infrastructure
   adapters implement these; components never import an adapter directly -
   they go through a hook, which goes through the shared container. */

import type {
  CapabilityReport,
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
