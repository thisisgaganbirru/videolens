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
