"use client";

import { useSearchParams } from "next/navigation";
import { IN_APP_ENTRY_KEY } from "@/application/backNavigation";

/* Which of the shell's four destinations is showing is a property of the URL,
   not of a component. It lives here because reading and writing that URL is
   orchestration — the same layer that owns `useAnalysisRun`'s state machine —
   and because two different route families (the app shell and the legal
   documents) both need to address the tabs without sharing a component tree.

   The tool lives at `/app` since Phase 5c (`/` is the landing page). The
   address is a query param (`/app?view=history`) rather than a route folder
   (`/app/history`) on purpose: one page component, one copy of the shell, and it
   survives `output: "export"`, which is what the Capacitor build ships. Route
   folders would mean four prerendered pages each carrying the whole shell, and
   a real document navigation on every tab switch. */

/** The four destinations, in nav order. */
export const MAIN_TABS = ["analyze", "history", "api-key", "releases"] as const;

export type MainTab = (typeof MAIN_TABS)[number];

/** The tab a bare `/app` shows, and the one that needs no param to address it. */
export const DEFAULT_MAIN_TAB: MainTab = "analyze";

/** Where the tool lives. `/` is the landing page (Phase 5c). */
export const APP_PATH = "/app";

const VIEW_PARAM = "view";

/**
 * Whether a pathname is the tool's own document. Three spellings, one page:
 * `next start` serves `/app`, a static host may add the slash, and the
 * Capacitor export can only reach the file as `/app.html` (its asset server
 * answers an extensionless path with `index.html`; see app/page.tsx).
 */
export function isAppPath(pathname: string): boolean {
  return pathname === APP_PATH || pathname === `${APP_PATH}/` || pathname === `${APP_PATH}.html`;
}

export function isMainTab(value: string | null | undefined): value is MainTab {
  return value != null && (MAIN_TABS as readonly string[]).includes(value);
}

/**
 * The address of a tab. Analyze is the bare route rather than
 * `/app?view=analyze` — a default that has to name itself isn't a default, and
 * the shared/bookmarked URL for "the app" should be `/app`.
 */
export function mainTabHref(tab: MainTab, base: string = APP_PATH): string {
  return tab === DEFAULT_MAIN_TAB ? base : `${base}?${VIEW_PARAM}=${tab}`;
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
  /* The marker says "the entry under this one is an app view", which is what
     the installed app's Back link asks on browsers without the Navigation API
     (older iOS standalone). Next's patched pushState copies its own router
     state in beside it. */
  /* Keep whichever spelling of the app document we are on (`/app.html` in the
     Capacitor export), so the pushed entry still reloads to this page. */
  const { pathname } = window.location;
  const base = isAppPath(pathname) ? pathname : APP_PATH;
  window.history.pushState({ [IN_APP_ENTRY_KEY]: true }, "", mainTabHref(tab, base));
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
