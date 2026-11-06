import type { DeviceTokenStore } from "@/domain/ports";

const DEVICE_TOKEN_KEY = "videolens-device-token";

/* The free-run device token (Phase 5b). Issued by `GET /api/free-runs`, sent
   as `X-Device-Token` on that request and on `POST /api/runs`. Every access is
   wrapped: a browser that refuses `localStorage` (some private modes) simply
   has no token, and the server issues a fresh one on the next status read —
   free runs must never be the reason the intake throws. */
export class LocalStorageDeviceTokenStore implements DeviceTokenStore {
  get(): string {
    try {
      return window.localStorage.getItem(DEVICE_TOKEN_KEY) || "";
    } catch {
      return "";
    }
  }

  set(token: string): void {
    try {
      if (token) window.localStorage.setItem(DEVICE_TOKEN_KEY, token);
      else window.localStorage.removeItem(DEVICE_TOKEN_KEY);
    } catch {
      /* no storage: the token lives only as long as the server's answer */
    }
  }
}
