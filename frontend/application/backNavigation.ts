/* "Back", for the installed app's pages that have no other way back.

   In an installed app on iOS there is no browser back button, and API key,
   Releases, Privacy and Terms are reached from the More sheet, so each of them
   carries a small Back link (`components/AppBackLink.tsx`). What "back" means
   is orchestration over the browser's history, so it lives here, beside
   `useMainTab`, rather than in the component.

   The rule: if the entry before this one is part of the app, go back to it, so
   the user lands on the view they came from (a tab on `/` or a legal route).
   Otherwise (a cold start straight onto the page, a link from outside) there is
   nothing in the app to go back to, and the destination is Analyze, the tool's
   home. */

/** History-state key `goToMainTab` stamps on the entries it pushes. */
export const IN_APP_ENTRY_KEY = "videolensInApp";

type NavigationEntryLike = { index: number };
type NavigationLike = { currentEntry: NavigationEntryLike | null };

/**
 * Whether the history entry before this one belongs to the app.
 *
 * Three signals, most reliable first:
 * 1. The Navigation API (Chromium; Safari 26+): `navigation.entries()` holds
 *    only this origin's entries, so any index above 0 is an in-app entry.
 * 2. The marker `goToMainTab` writes into each entry it pushes: an entry that
 *    was pushed in place by a tab switch has, by construction, an app view
 *    under it. Covers older iOS standalone for API key and Releases.
 * 3. A same-origin referrer: Privacy and Terms are document navigations
 *    (plain `<a>` from the More sheet), so the page that linked here is the
 *    previous entry.
 */
export function hasInAppPrevious(): boolean {
  const navigation = (window as Window & { navigation?: NavigationLike }).navigation;
  const index = navigation?.currentEntry?.index;
  if (typeof index === "number") return index > 0;

  const state: unknown = window.history.state;
  if (state && typeof state === "object" && (state as Record<string, unknown>)[IN_APP_ENTRY_KEY]) {
    return true;
  }

  if (!document.referrer) return false;
  try {
    return new URL(document.referrer).origin === window.location.origin;
  } catch {
    return false;
  }
}
