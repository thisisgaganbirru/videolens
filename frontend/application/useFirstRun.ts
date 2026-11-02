"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import { firstRunStore, sharedUrlSource } from "@/infrastructure/container";
import { goToMainTab, type MainTab } from "@/application/useMainTab";

/* Phase 5d: the installed app's cold-start splash and first-run Welcome, as one
   small module store, because the two have to take turns — Welcome is a modal
   <dialog> in the top layer, which would paint over the splash if it opened
   while the splash was still up.

   Neither exists in a browser tab. Both read `<html data-shell>`, which the
   pre-paint script in app/layout.tsx stamps, never React state.

   - Splash: `<html data-splash>` is set pre-paint by SPLASH_INIT_SCRIPT
     (application/firstRunScripts.ts). `useSplashHandOff` takes it down once
     the page has been up for SPLASH_MIN_MS since navigation start — so a slow
     cold start never waits *extra*, and nothing here ever waits on the network.
   - Welcome: shown once per device, then remembered (firstRunStore), and never
     on a launch that carried a link — a share, or a shortcut / deep link to a
     particular view. A share that lands while Welcome is open closes it
     without marking it seen, so the link reaches the intake underneath (which
     is mounted the whole time) and Welcome comes back on a later launch. */

const SPLASH_ATTR = "data-splash";
/** From navigation start, not from mount: the splash should end at the same
 *  moment however long the bundle took. Short on purpose — on Android it
 *  follows the native launch splash (docs/frontend/first-run.md). */
const SPLASH_MIN_MS = 650;
/** Must match the opacity transition on `.splash` in app/first-run.css. */
const SPLASH_FADE_MS = 200;

type FirstRunState = { splash: boolean; welcome: boolean };

const SERVER_STATE: FirstRunState = { splash: false, welcome: false };

/* Read once, when this module is evaluated — i.e. as the page's bundle loads,
   before React hydrates and before useSharedUrl's effect drains the share out
   of the address and storage. Reading it later would always say "no link". */
const launchCarriesLink: boolean = (() => {
  if (typeof window === "undefined") return false;
  try {
    const view = new URLSearchParams(window.location.search).get("view");
    return sharedUrlSource.pending() || (view !== null && view !== "analyze");
  } catch {
    return false;
  }
})();

let state: FirstRunState | null = null;
const listeners = new Set<() => void>();

function initialState(): FirstRunState {
  const root = document.documentElement;
  const installed = root.getAttribute("data-shell") === "app";
  const splash = root.hasAttribute(SPLASH_ATTR);
  const welcome = installed && !launchCarriesLink && !firstRunStore.welcomeSeen();
  /* Once on screen it counts for this session even if a share then closes it,
     so a reload does not bring it straight back. */
  if (welcome) firstRunStore.markWelcomeShownThisSession();
  return { splash, welcome };
}

function getSnapshot(): FirstRunState {
  if (state === null) state = initialState();
  return state;
}

function getServerSnapshot(): FirstRunState {
  return SERVER_STATE;
}

function update(patch: Partial<FirstRunState>): void {
  const current = getSnapshot();
  state = { ...current, ...patch };
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  /* A share arriving while Welcome is up: step aside, keep it unseen. */
  const unsubscribeShare = sharedUrlSource.subscribe(() => {
    if (getSnapshot().welcome) update({ welcome: false });
  });
  return () => {
    listeners.delete(listener);
    unsubscribeShare();
  };
}

function useFirstRunState(): FirstRunState {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

/**
 * Takes the cold-start splash down. Call from the splash component only.
 * Drives `<html data-splash>` directly: the attribute was set before React
 * existed, and CSS keys off it.
 */
export function useSplashHandOff(): void {
  useEffect(() => {
    const root = document.documentElement;
    if (!root.hasAttribute(SPLASH_ATTR)) return;
    /* Counted as played from the moment it is on screen, so a reload in the
       middle of it does not start it over. */
    firstRunStore.markSplashShown();

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let fadeTimer: number | undefined;
    const holdTimer = window.setTimeout(() => {
      root.setAttribute(SPLASH_ATTR, "leaving");
      fadeTimer = window.setTimeout(() => {
        root.removeAttribute(SPLASH_ATTR);
        update({ splash: false });
      }, reduce ? 0 : SPLASH_FADE_MS);
    }, Math.max(0, SPLASH_MIN_MS - performance.now()));

    return () => {
      window.clearTimeout(holdTimer);
      if (fadeTimer !== undefined) window.clearTimeout(fadeTimer);
    };
  }, []);
}

/**
 * Whether the first-run Welcome is on screen, and how it is dismissed.
 * `open` is false until the splash is gone, so the two never overlap.
 */
export function useWelcome(): { open: boolean; dismiss: (next: MainTab) => void } {
  const { splash, welcome } = useFirstRunState();

  const dismiss = useCallback((next: MainTab) => {
    firstRunStore.markWelcomeSeen();
    update({ welcome: false });
    goToMainTab(next);
  }, []);

  return { open: welcome && !splash, dismiss };
}
