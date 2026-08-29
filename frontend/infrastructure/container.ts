/* Composition root: builds every concrete adapter once and wires them
   together, mirroring the backend's container.py. Hooks in application/
   import instances from here - they never construct an adapter directly. */

import { LocalStorageApiKeyStore } from "./apiKeyStore";
import { FetchCapabilitiesGateway } from "./capabilitiesGateway";
import { FetchRunsGateway } from "./runsGateway";
import { ApiUpdateChecker } from "./updateCheck";
import { WebShareUrlSource } from "./sharedUrlSource";
import { FetchVersionLogGateway } from "./versionLogGateway";

export const apiKeyStore = new LocalStorageApiKeyStore();
export const runsGateway = new FetchRunsGateway(apiKeyStore);
export const capabilitiesGateway = new FetchCapabilitiesGateway();
export const versionLogGateway = new FetchVersionLogGateway();
export const updateChecker = new ApiUpdateChecker();
export const sharedUrlSource = new WebShareUrlSource();
