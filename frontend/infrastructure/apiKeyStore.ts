import type { ApiKeyStore } from "@/domain/ports";

const GEMINI_API_KEY_STORAGE_KEY = "videolens-gemini-api-key";

// Bring-your-own-key: kept only on-device. Sent with run creation so the
// user's own quota is spent instead of the shared one - never written
// anywhere else, never logged.
export class LocalStorageApiKeyStore implements ApiKeyStore {
  private readonly listeners = new Set<() => void>();

  get(): string {
    try {
      return window.localStorage.getItem(GEMINI_API_KEY_STORAGE_KEY) || "";
    } catch {
      return "";
    }
  }

  set(apiKey: string): void {
    const trimmed = apiKey.trim();
    /* Storage can throw (private mode, blocked site data). Refinement 1 (#5):
       the key is then simply not saved; `get()` keeps reading "" and the
       panel shows no saved key, which is the truth. */
    try {
      if (trimmed) {
        window.localStorage.setItem(GEMINI_API_KEY_STORAGE_KEY, trimmed);
      } else {
        window.localStorage.removeItem(GEMINI_API_KEY_STORAGE_KEY);
      }
    } catch {
      /* not saved */
    }
    this.listeners.forEach((listener) => listener());
  }

  /* Same-tab writes notify directly (above); another tab's arrive as a
     `storage` event. The window listener exists only while subscribed. Added
     in Phase 5b so the free-run banner disappears the moment a key is saved. */
  subscribe(listener: () => void): () => void {
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === GEMINI_API_KEY_STORAGE_KEY) listener();
    };
    this.listeners.add(listener);
    window.addEventListener("storage", onStorage);
    return () => {
      this.listeners.delete(listener);
      window.removeEventListener("storage", onStorage);
    };
  }
}
