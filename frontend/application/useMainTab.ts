"use client";

import { useSearchParams } from "next/navigation";

/* Which of the shell's four destinations is showing is a property of the URL,
   not of a component. It lives here because reading and writing that URL is
   orchestration — the same layer that owns `useAnalysisRun`'s state machine —
   and because two different route families (the app shell and the legal
   documents) both need to address the tabs without sharing a component tree.

   The address is a query param (`/?view=history`) rather than a route folder
   (`/history`) on purpose: one page component, one copy of the shell, and it
   survives `output: "export"`, which is what the Capacitor build ships. Route
   folders would mean four prerendered pages each carrying the whole shell, and
   a real document navigation on every tab switch. */

/** The four destinations, in nav order. */
export const MAIN_TABS = ["analyze", "history", "api-key", "releases"] as const;

export type MainTab = (typeof MAIN_TABS)[number];

/** The tab a bare `/` shows, and the one that needs no param to address it. */
export const DEFAULT_MAIN_TAB: MainTab = "analyze";

const VIEW_PARAM = "view";

export function isMainTab(value: string | null | undefined): value is MainTab {
  return value != null && (MAIN_TABS as readonly string[]).includes(value);
}

/**
 * The address of a tab. Analyze is the bare route rather than
 * `/?view=analyze` — a default that has to name itself isn't a default, and
 * the shared/bookmarked URL for "the app" should be `/`.
 */
export function mainTabHref(tab: MainTab): string {
  return tab === DEFAULT_MAIN_TAB ? "/" : `/?${VIEW_PARAM}=${tab}`;
}

/** The tab the current browser URL names. Client-only; reads `location`. */
function tabFromLocation(): MainTab {
  const raw = new URLSearchParams(window.location.search).get(VIEW_PARAM);
  return isMainTab(raw) ? raw : DEFAULT_MAIN_TAB;
}

/**
 * Switch tabs from a route that is *already* the app shell.
 *
 * `history.pushState` rather than `router.push`: Next has supported the native
 * History API for search-param updates since 14.1 and keeps `useSearchParams`
 * in sync with it, and unlike a router navigation it never asks for an RSC
 * payload — which matters because the Capacitor build is a static export with
 * no server to ask. The shell is not unmounted, so nothing refetches and no
 * pane loses its scroll position.
 *
 * `push`, not `replace`: the URL is now a real address, so a tab switch is a
 * real navigation and back should undo it. On Android the hardware back button
 * therefore walks back through the tabs and only leaves the app from the first
 * entry — which is also what makes "open a run from history, press back" land
 * on the history list instead of dropping the user out of the app.
 */
export function goToMainTab(tab: MainTab): void {
  if (tabFromLocation() === tab) return;
  window.history.pushState(null, "", mainTabHref(tab));
}

/**
 * The active tab, tracked from the URL.
 *
 * Calls `useSearchParams`, so every caller must sit under a `<Suspense>`
 * boundary — on a statically rendered route (all of them here) Next resolves
 * search params on the client and renders the nearest fallback into the
 * prerendered HTML. Without the boundary `next build` fails outright.
 * `app/page.tsx` owns that boundary; see the note there for what it falls back
 * to and why.
 */
export function useMainTab(): MainTab {
  const raw = useSearchParams().get(VIEW_PARAM);
  return isMainTab(raw) ? raw : DEFAULT_MAIN_TAB;
}
