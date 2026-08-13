/* Interfaces the application layer (hooks) depends on. Infrastructure
   adapters implement these; components never import an adapter directly -
   they go through a hook, which goes through the shared container. */

import type { MediaSource, RunCreateResponse, RunListResponse, RunStatusResponse } from "./entities";

export interface RunsGateway {
  createRun(source: MediaSource): Promise<RunCreateResponse>;
  getRun(runId: string): Promise<RunStatusResponse>;
  listRuns(): Promise<RunListResponse>;
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
