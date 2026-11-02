/* Composition root: builds every concrete adapter once and wires them
   together, mirroring the backend's container.py. Hooks in application/
   import instances from here - they never construct an adapter directly. */

import { LocalStorageApiKeyStore } from "./apiKeyStore";
import { FetchCapabilitiesGateway } from "./capabilitiesGateway";
import { LocalStorageDeviceTokenStore } from "./deviceTokenStore";
import { FetchFreeRunsGateway } from "./freeRunsGateway";
import { IndexedDbHistoryStore } from "./historyStore";
import { FetchRunsGateway } from "./runsGateway";
import { ApiUpdateChecker } from "./updateCheck";
import { WebShareUrlSource } from "./sharedUrlSource";
import { FetchVersionLogGateway } from "./versionLogGateway";
import { CapacitorSystemBarsStyler } from "./systemBars";
import { BrowserFirstRunStore } from "./firstRunStore";

export const apiKeyStore = new LocalStorageApiKeyStore();
/* One device-token store behind both the status read (which may replace the
   token) and run creation (which sends it), so a refreshed token is the one
   the next submit carries. */
export const deviceTokenStore = new LocalStorageDeviceTokenStore();
export const runsGateway = new FetchRunsGateway(apiKeyStore, deviceTokenStore);
export const freeRunsGateway = new FetchFreeRunsGateway(deviceTokenStore);
export const capabilitiesGateway = new FetchCapabilitiesGateway();
export const versionLogGateway = new FetchVersionLogGateway();
export const updateChecker = new ApiUpdateChecker();
export const sharedUrlSource = new WebShareUrlSource();
export const systemBarsStyler = new CapacitorSystemBarsStyler();
export const historyStore = new IndexedDbHistoryStore();
export const firstRunStore = new BrowserFirstRunStore();
