import type { ActiveRunStore } from "@/domain/ports";

/* sessionStorage, not localStorage: it is per tab and survives a reload but
   not the tab, which is exactly "the run this tab was watching". Every access
   is wrapped, as everywhere else in the app: storage can throw outright in a
   private window or with site data blocked, and then a reload simply lands
   on a fresh intake, as it always did. */
const KEY = "videolens-active-run";

export class SessionStorageActiveRunStore implements ActiveRunStore {
  get(): string | null {
    try {
      return window.sessionStorage.getItem(KEY);
    } catch {
      return null;
    }
  }

  set(runId: string): void {
    try {
      window.sessionStorage.setItem(KEY, runId);
    } catch {
      /* not remembered; a reload starts fresh */
    }
  }

  clear(): void {
    try {
      window.sessionStorage.removeItem(KEY);
    } catch {
      /* nothing stored that we could clear */
    }
  }
}
