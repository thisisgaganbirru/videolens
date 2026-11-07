import type { UpdateDismissalStore } from "@/domain/ports";

const DISMISSED_UPDATE_KEY = "videolens-update-dismissed";

/* Refinement 9: the update banner's dismiss, remembered per build. Only the
   newest dismissed `versionCode` is kept; the banner compares against it, so a
   later build (a higher code) shows again. Storage can throw (private mode,
   blocked site data) — then nothing is remembered and the banner shows, which
   errs on the side of telling the user an update exists. */
export class LocalStorageUpdateDismissalStore implements UpdateDismissalStore {
  dismissedCode(): number | null {
    try {
      const raw = window.localStorage.getItem(DISMISSED_UPDATE_KEY);
      if (raw === null) return null;
      const code = Number(raw);
      return Number.isFinite(code) ? code : null;
    } catch {
      return null;
    }
  }

  dismiss(versionCode: number): void {
    try {
      window.localStorage.setItem(DISMISSED_UPDATE_KEY, String(versionCode));
    } catch {
      /* not remembered; the banner still hides for this visit */
    }
  }
}
