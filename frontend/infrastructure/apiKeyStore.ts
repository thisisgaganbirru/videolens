import type { ApiKeyStore } from "@/domain/ports";

const GEMINI_API_KEY_STORAGE_KEY = "videolens-gemini-api-key";

// Bring-your-own-key: kept only on-device. Sent with run creation so the
// user's own quota is spent instead of the shared one - never written
// anywhere else, never logged.
export class LocalStorageApiKeyStore implements ApiKeyStore {
  get(): string {
    return window.localStorage.getItem(GEMINI_API_KEY_STORAGE_KEY) || "";
  }

  set(apiKey: string): void {
    const trimmed = apiKey.trim();
    if (trimmed) {
      window.localStorage.setItem(GEMINI_API_KEY_STORAGE_KEY, trimmed);
    } else {
      window.localStorage.removeItem(GEMINI_API_KEY_STORAGE_KEY);
    }
  }
}
