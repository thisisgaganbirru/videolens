"use client";

import { useEffect, useSyncExternalStore } from "react";
import { ApiError, NetworkError } from "@/domain/errors";

/* Refinement 4 (LCH-06): launching with the server unreachable used to give
   Analyze no hint at all. The free-runs pill and the capability notice both go
   quiet on a failed read (deliberately — see useFreeRuns and useCapabilities),
   so the screen looked exactly like a healthy one until a submit failed.

   This module is the one place that knows "the last read could not reach the
   server". It does not fetch anything itself: the two reads that already
   happen on launch report into it (`noteReadResult`), and it tells them when
   to try again (`onReconnectChance`). So no new request exists on a healthy
   launch, and the two hooks keep their own policies — they just stop being
   the only ones who knew.

   - unreachable: a read failed with `NetworkError` (no response at all), or
     with a 5xx `ApiError` (refinement 10: a proxy's 502/503 for a service
     that is down). Any other `ApiError` — the server answered, badly — is not
     a reachability problem and clears the flag, because the server evidently
     is there.
   - offline: `navigator.onLine` is false. Read live; cheap and authoritative
     in the "no network at all" direction (it can be true while the server is
     still unreachable, which is what the flag above is for).

   Retry is quiet: the `online` event, the window regaining focus, and the
   page becoming visible again each give the reads a chance, but only while
   the notice is up — a healthy app makes no extra requests. */

let unreachable = false;
const listeners = new Set<() => void>();
const reconnectListeners = new Set<() => void>();

function publish(next: boolean) {
  if (next === unreachable) return;
  unreachable = next;
  listeners.forEach((listener) => listener());
}

/** A launch-time read finished. `error` is what it threw, or undefined on
 *  success. A `NetworkError` means "could not reach the server", and so does
 *  a 5xx `ApiError` (refinement 10): with the service down, Railway's edge
 *  answers every path with a 502/503, so "an answer came back" no longer
 *  proves the app server is there. A 4xx is the server itself refusing, and
 *  keeps clearing the flag. */
export function noteReadResult(error?: unknown): void {
  publish(
    error instanceof NetworkError ||
      (error instanceof ApiError && typeof error.status === "number" && error.status >= 500),
  );
}

/** Register a read to repeat when the connection may be back. Returns the
 *  unsubscribe. Each listener decides for itself whether it still needs to. */
export function onReconnectChance(listener: () => void): () => void {
  reconnectListeners.add(listener);
  return () => {
    reconnectListeners.delete(listener);
  };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("online", listener);
  window.addEventListener("offline", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("online", listener);
    window.removeEventListener("offline", listener);
  };
}

function isOffline(): boolean {
  try {
    return navigator.onLine === false;
  } catch {
    return false;
  }
}

/* A string, so useSyncExternalStore compares by value. */
type Reachability = "ok" | "offline" | "unreachable";
const snapshot = (): Reachability => (isOffline() ? "offline" : unreachable ? "unreachable" : "ok");
/* The prerendered HTML cannot know; it renders the healthy screen. */
const serverSnapshot = (): Reachability => "ok";

/**
 * Whether Analyze should say the server cannot be reached right now. Call
 * once, from the always-mounted shell (HomeScreen), next to the two reads it
 * watches. Also owns the quiet retry while the answer is "no".
 */
export function useServerReachability(): Reachability {
  const state = useSyncExternalStore(subscribe, snapshot, serverSnapshot);

  useEffect(() => {
    if (state === "ok") return;
    let last = 0;
    const chance = () => {
      if (isOffline()) return;
      /* focus and visibilitychange often fire together; one retry, not two. */
      const now = Date.now();
      if (now - last < 1500) return;
      last = now;
      reconnectListeners.forEach((listener) => listener());
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") chance();
    };
    window.addEventListener("online", chance);
    window.addEventListener("focus", chance);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("online", chance);
      window.removeEventListener("focus", chance);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [state]);

  return state;
}
