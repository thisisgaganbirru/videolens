import type { FirstRunStore } from "@/domain/ports";

/* Phase 5d: the installed app's first-run memory.

   `videolens-welcome-v1` (localStorage) — Welcome was dismissed with one of its
   buttons. Versioned so a future, materially different Welcome can be shown
   once more by bumping it.

   Both session keys live in sessionStorage, i.e. one launch of the installed
   app (a standalone PWA window, or the Capacitor WebView's process):
   `videolens-welcome-session` — Welcome was on screen this session, so a
   reload or an Android back-and-return does not show it twice;
   `videolens-splash-session` — the cold-start splash has played. The splash's
   pre-paint script (application/firstRunScripts.ts) reads that key directly,
   which is why it is exported.

   Every access is in try/catch. With no storage at all, a module-level flag
   still holds "seen" for the life of the page, so Welcome is at most once per
   page load there and never loops. */

export const WELCOME_STORAGE_KEY = "videolens-welcome-v1";
export const WELCOME_SESSION_KEY = "videolens-welcome-session";
export const SPLASH_SESSION_KEY = "videolens-splash-session";

function read(storage: () => Storage, key: string): boolean {
  try {
    return storage().getItem(key) === "1";
  } catch {
    return false;
  }
}

function write(storage: () => Storage, key: string): void {
  try {
    storage().setItem(key, "1");
  } catch {
    /* blocked or full: the in-memory flag below still covers this page */
  }
}

const local = () => window.localStorage;
const session = () => window.sessionStorage;

export class BrowserFirstRunStore implements FirstRunStore {
  private welcomeSeenInMemory = false;

  welcomeSeen(): boolean {
    if (typeof window === "undefined") return true;
    return (
      this.welcomeSeenInMemory || read(local, WELCOME_STORAGE_KEY) || read(session, WELCOME_SESSION_KEY)
    );
  }

  markWelcomeSeen(): void {
    this.welcomeSeenInMemory = true;
    write(local, WELCOME_STORAGE_KEY);
    write(session, WELCOME_SESSION_KEY);
  }

  markWelcomeShownThisSession(): void {
    this.welcomeSeenInMemory = true;
    write(session, WELCOME_SESSION_KEY);
  }

  markSplashShown(): void {
    write(session, SPLASH_SESSION_KEY);
  }
}
