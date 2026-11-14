/* Composition root: builds every concrete adapter once and wires them
   together, mirroring the backend's container.py. Hooks in application/
   import instances from here - they never construct an adapter directly. */

import type { CallerIdentity } from "@/domain/ports";
import { SessionStorageActiveRunStore } from "./activeRunStore";
import { FetchAccountGateway } from "./accountGateway";
import { FetchBillingGateway } from "./billingGateway";
import { ApiClient } from "./apiClient";
import { buildAuthSession } from "./authSession";
import { LocalStorageApiKeyStore } from "./apiKeyStore";
import { FetchCapabilitiesGateway } from "./capabilitiesGateway";
import { LocalStorageDeviceTokenStore } from "./deviceTokenStore";
import { FetchFreeRunsGateway } from "./freeRunsGateway";
import { FetchLimitsGateway } from "./limitsGateway";
import { IndexedDbHistoryStore } from "./historyStore";
import { FetchRunsGateway } from "./runsGateway";
import { MemoryServerAuthStatus } from "./serverAuthStatus";
import { ApiUpdateChecker } from "./updateCheck";
import { LocalStorageUpdateDismissalStore } from "./updateDismissalStore";
import { WebShareUrlSource } from "./sharedUrlSource";
import { FetchVersionLogGateway } from "./versionLogGateway";
import { CapacitorSystemBarsStyler } from "./systemBars";
import { BrowserFirstRunStore } from "./firstRunStore";
import { CapacitorNativeShell } from "./nativeShell";
import { CapacitorDocumentExporter } from "./documentExporter";
import { CapacitorNativeThemeMirror } from "./nativeTheme";

export const apiKeyStore = new LocalStorageApiKeyStore();
/* One device-token store behind both the status read (which may replace the
   token) and run creation (which sends it), so a refreshed token is the one
   the next submit carries. */
export const deviceTokenStore = new LocalStorageDeviceTokenStore();
/* Supabase when both NEXT_PUBLIC_SUPABASE_* variables are set, otherwise a
   session that is never signed in (auth phase 2). */
export const authSession = buildAuthSession();
/* The caller's identity on every request that speaks for them: client id,
   device token, and the bearer token when signed in. */
/* Whether this server verifies sign-in tokens, heard from the capability
   report; the bearer goes out only when it does. */
export const serverAuthStatus = new MemoryServerAuthStatus();
export const apiClient = new ApiClient(authSession, deviceTokenStore, serverAuthStatus);
/* The identity the last caller request went out as (History run ownership). */
export const callerIdentity: CallerIdentity = apiClient;
export const runsGateway = new FetchRunsGateway(apiClient, apiKeyStore);
export const freeRunsGateway = new FetchFreeRunsGateway(apiClient, deviceTokenStore);
export const accountGateway = new FetchAccountGateway(apiClient);
/* The paid plan (2026-11-13): Stripe-hosted pages, reached by redirect. */
export const billingGateway = new FetchBillingGateway(apiClient);
/* Upload limits per tier (2026-11-13); public, no caller identity. */
export const limitsGateway = new FetchLimitsGateway();
export const capabilitiesGateway = new FetchCapabilitiesGateway(serverAuthStatus);
export const versionLogGateway = new FetchVersionLogGateway();
export const updateChecker = new ApiUpdateChecker();
export const updateDismissalStore = new LocalStorageUpdateDismissalStore();
export const sharedUrlSource = new WebShareUrlSource();
export const systemBarsStyler = new CapacitorSystemBarsStyler();
export const historyStore = new IndexedDbHistoryStore();
export const firstRunStore = new BrowserFirstRunStore();
export const nativeShell = new CapacitorNativeShell();
export const documentExporter = new CapacitorDocumentExporter();
export const nativeThemeMirror = new CapacitorNativeThemeMirror();
export const activeRunStore = new SessionStorageActiveRunStore();
