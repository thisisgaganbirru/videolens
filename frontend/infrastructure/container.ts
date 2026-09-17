/* Composition root: builds every concrete adapter once and wires them
   together, mirroring the backend's container.py. Hooks in application/
   import instances from here - they never construct an adapter directly. */

import { FetchAccountGateway } from "./accountGateway";
import { ApiClient } from "./apiClient";
import { LocalStorageApiKeyStore } from "./apiKeyStore";
import { buildAuthSession } from "./authSession";
import { FetchCapabilitiesGateway } from "./capabilitiesGateway";
import { FetchLibraryGateway } from "./libraryGateway";
import { FetchRunsGateway } from "./runsGateway";
import { ApiUpdateChecker } from "./updateCheck";
import { WebShareUrlSource } from "./sharedUrlSource";
import { FetchVersionLogGateway } from "./versionLogGateway";

export const apiKeyStore = new LocalStorageApiKeyStore();
/* Null when NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is unset: every request then
   goes out anonymous, exactly as before accounts existed. */
export const authSession = buildAuthSession();
/* One client, so the three caller-scoped gateways send one identity. */
const apiClient = new ApiClient(apiKeyStore, authSession);
export const runsGateway = new FetchRunsGateway(apiClient);
export const accountGateway = new FetchAccountGateway(apiClient);
export const libraryGateway = new FetchLibraryGateway(apiClient);
export const capabilitiesGateway = new FetchCapabilitiesGateway();
export const versionLogGateway = new FetchVersionLogGateway();
export const updateChecker = new ApiUpdateChecker();
export const sharedUrlSource = new WebShareUrlSource();
