"use client";

import { useSearchParams } from "next/navigation";
import { IN_APP_ENTRY_KEY } from "@/application/backNavigation";
import { nativeShell } from "@/infrastructure/container";

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

/** The destinations, in nav order. `account` (auth phase 2) is offered only
 *  where sign-in is available; see `navTabs`. */
export const MAIN_TABS = ["analyze", "history", "api-key", "releases", "account"] as const;

export type MainTab = (typeof MAIN_TABS)[number];

/**
 * The tabs a nav should draw. The Account tab is left out unless the caller
 * says sign-in is available (the deployment has a provider and its `auth`
 * capability reports `ok`). Only `/app` knows that, so the legal and offline
 * routes, which pass nothing, draw the tabs without it. Its address still
 * works everywhere: `/app?view=account` renders the panel, which explains
 * itself when sign-in is off.
 */
export function navTabs(showAccount = false): readonly MainTab[] {
  return showAccount ? MAIN_TABS : MAIN_TABS.filter((tab) => tab !== "account");
}

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
export function goToMainTab(tab: MainTab, options: { push?: boolean } = {}): void {
  if (tabFromLocation() === tab) return;
  /* The marker says "the entry under this one is an app view", which is what
     the installed app's Back link asks on browsers without the Navigation API
     (older iOS standalone). Next's patched pushState copies its own router
     state in beside it. */
  /* Keep whichever spelling of the app document we are on (`/app.html` in the
     Capacitor export), so the pushed entry still reloads to this page. */
  const { pathname } = window.location;
  const base = isAppPath(pathname) ? pathname : APP_PATH;
  const href = mainTabHref(tab, base);

  /* Android shell (refinement 1, #4): a tab switch replaces the entry. The
     hardware back button there means "back out of what I opened", not "undo
     my last tab tap" — otherwise five taps between Analyze and History cost
     five presses to leave. `decideBack` sends a non-Analyze tab with nothing
     under it to Analyze, then exits. Opening a run from History passes
     `push`, so back from that run still returns to the list.

     A fresh state object, never `history.state` itself: Next's patched
     replaceState skips its URL sync when handed its own state (`__NA`). The
     in-app marker is carried over only if this entry already had one. */
  if (nativeShell.isNative() && !options.push) {
    const current: unknown = window.history.state;
    const marked =
      !!current && typeof current === "object" && !!(current as Record<string, unknown>)[IN_APP_ENTRY_KEY];
    window.history.replaceState(marked ? { [IN_APP_ENTRY_KEY]: true } : {}, "", href);
    return;
  }
  window.history.pushState({ [IN_APP_ENTRY_KEY]: true }, "", href);
}

/**
 * Whether this page is served by Capacitor's Android asset server (native,
 * `localhost`, no port) — the same test the landing page's head script uses
 * before its `.html` hop. Live reload (`localhost:3005`) and every browser
 * answer false.
 */
export function isCapacitorAssetServer(): boolean {
  if (typeof window === "undefined") return false;
  const { hostname, port } = window.location;
  return nativeShell.isNative() && hostname === "localhost" && !port;
}

/**
 * Refinement 9: one spelling of the tool's address in the installed app.
 *
 * On the asset server the real document is `/app.html` (`/app` only works by
 * way of `index.html` and the head script's hop), and a cold start, a reload
 * and the legal pages' Back (a history step back) all land there. But the
 * dock and the legal pages' links are client-side navigations to `/app`, so
 * the same screen answered to two addresses depending on how it was reached.
 * This rewrites `/app` to `/app.html` in place, keeping the query, the hash
 * and the in-app marker — the same replaceState `goToMainTab` already does on
 * that shell. No navigation, no reload. Everywhere else it does nothing: the
 * web keeps `/app`, which is the right spelling for `next start` and static
 * hosts.
 */
export function canonicalizeAppPath(): void {
  if (!isCapacitorAssetServer()) return;
  const { pathname, search, hash } = window.location;
  if (pathname !== APP_PATH && pathname !== `${APP_PATH}/`) return;
  const current: unknown = window.history.state;
  const marked =
    !!current && typeof current === "object" && !!(current as Record<string, unknown>)[IN_APP_ENTRY_KEY];
  window.history.replaceState(marked ? { [IN_APP_ENTRY_KEY]: true } : {}, "", `${APP_PATH}.html${search}${hash}`);
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

/**
 * Reads one query param from the current address and removes it in place
 * (billing return, 2026-11-13: `/app?view=account&billing=success`), so a
 * reload or a shared link does not repeat what it announced. Keeps the tab,
 * the other params, the hash and the in-app marker; a fresh state object for
 * the same reason as `goToMainTab` (Next then syncs `useSearchParams`).
 * Client-only. Returns null when the param is absent.
 */
export function takeSearchParam(name: string): string | null {
  const url = new URL(window.location.href);
  const value = url.searchParams.get(name);
  if (value === null) return null;
  url.searchParams.delete(name);
  const current: unknown = window.history.state;
  const marked =
    !!current && typeof current === "object" && !!(current as Record<string, unknown>)[IN_APP_ENTRY_KEY];
  window.history.replaceState(marked ? { [IN_APP_ENTRY_KEY]: true } : {}, "", `${url.pathname}${url.search}${url.hash}`);
  return value;
}
