/* The intake's media-use terms flag, shared by the form (the checkbox) and
   the expired view's "Choose the file again" (refinement 9), which has to know
   — inside the tap, before anything re-renders — whether it may open the file
   picker straight away.

   Storage can throw (private mode, blocked site data). Refinement 1 (#5): an
   unreadable flag reads as "not accepted" and an unwritable one is simply not
   remembered — the box still works for this visit. */

/* Bump the version whenever the Terms change materially: a new key means
   everyone sees the box unticked and accepts the updated Terms once. Add the
   key it replaces to RETIRED_KEYS so it is cleared from storage.
   v2 (2026-11-13): the Terms were updated alongside BYOK and sign-in.
   v3 (2026-11-13): the Terms gained the Paid plan section (billing).
   v4 (2026-11-14): paid accounts' results are stored on the server, and a
   deleted account is held for 30 days (Privacy and Terms). */
const MEDIA_TERMS_ACCEPTANCE_KEY = "videolens-media-terms-v4";
const RETIRED_KEYS = ["videolens-media-terms-v1", "videolens-media-terms-v2", "videolens-media-terms-v3"];

function clearRetiredKeys(): void {
  for (const key of RETIRED_KEYS) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* storage unavailable; nothing to clear */
    }
  }
}

export function readTermsAccepted(): boolean {
  clearRetiredKeys();
  try {
    return window.localStorage.getItem(MEDIA_TERMS_ACCEPTANCE_KEY) === "accepted";
  } catch {
    return false;
  }
}

export function writeTermsAccepted(accepted: boolean): void {
  clearRetiredKeys();
  try {
    if (accepted) window.localStorage.setItem(MEDIA_TERMS_ACCEPTANCE_KEY, "accepted");
    else window.localStorage.removeItem(MEDIA_TERMS_ACCEPTANCE_KEY);
  } catch {
    /* not remembered; nothing else to do */
  }
}

/** What the file input accepts, wherever a picker is opened. */
export const MEDIA_FILE_ACCEPT = ".mp3,.mp4,.mov,audio/mpeg,video/mp4,video/quicktime";
