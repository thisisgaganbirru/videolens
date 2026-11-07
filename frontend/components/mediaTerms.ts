/* The intake's media-use terms flag, shared by the form (the checkbox) and
   the expired view's "Choose the file again" (refinement 9), which has to know
   — inside the tap, before anything re-renders — whether it may open the file
   picker straight away.

   Storage can throw (private mode, blocked site data). Refinement 1 (#5): an
   unreadable flag reads as "not accepted" and an unwritable one is simply not
   remembered — the box still works for this visit. */

const MEDIA_TERMS_ACCEPTANCE_KEY = "videolens-media-terms-v1";

export function readTermsAccepted(): boolean {
  try {
    return window.localStorage.getItem(MEDIA_TERMS_ACCEPTANCE_KEY) === "accepted";
  } catch {
    return false;
  }
}

export function writeTermsAccepted(accepted: boolean): void {
  try {
    if (accepted) window.localStorage.setItem(MEDIA_TERMS_ACCEPTANCE_KEY, "accepted");
    else window.localStorage.removeItem(MEDIA_TERMS_ACCEPTANCE_KEY);
  } catch {
    /* not remembered; nothing else to do */
  }
}

/** What the file input accepts, wherever a picker is opened. */
export const MEDIA_FILE_ACCEPT = ".mp3,.mp4,.mov,audio/mpeg,video/mp4,video/quicktime";
