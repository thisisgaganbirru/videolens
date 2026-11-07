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

   - unreachable: at least one read's latest result failed with
     `NetworkError` (no response at all), or with a 5xx `ApiError`
     (refinement 10: a proxy's 502/503 for a service that is down). Any other
     `ApiError` (the server answered, badly) is not a reachability problem
     and counts as healthy for that read, because the server evidently is
     there.

     Refinement 11 (D-R10-1): this used to be ONE shared boolean that each
     read overwrote, so when only one of the two launch reads hit a 5xx the
     other one's success cleared it again: last read wins, and a partial
     outage showed nothing. Each read now keeps its own last result, keyed by
     source, and the notice is up while ANY of them is failing. It clears
     only once every read has since come back healthy (a later launch,
     resume or refocus round re-reads the failing ones, see
     `onReconnectChance`). A read that is no longer made at all (free runs
     with a saved key) forgets its result (`forgetReadResult`), so a stale
     failure cannot hold the notice up with nothing left to retry it.
   - offline: `navigator.onLine` is false. Read live; cheap and authoritative
     in the "no network at all" direction (it can be true while the server is
     still unreachable, which is what the flag above is for).

   Retry is quiet: the `online` event, the window regaining focus, and the
   page becoming visible again each give the reads a chance, but only while
   the notice is up — a healthy app makes no extra requests. */

/** The launch-time reads that report here. One entry each, so one read's
 *  success can never hide another's failure. */
export type ReadSource = "free-runs" | "capabilities";

const failing = new Set<ReadSource>();
let unreachable = false;
const listeners = new Set<() => void>();
const reconnectListeners = new Set<() => void>();

function recompute() {
  const next = failing.size > 0;
  if (next === unreachable) return;
  unreachable = next;
  listeners.forEach((listener) => listener());
}

/** Whether `error` means "could not reach the server": a `NetworkError`, or
 *  a 5xx `ApiError` (refinement 10). With the service down, Railway's edge
 *  answers every path with a 502/503, so "an answer came back" no longer
 *  proves the app server is there. A 4xx is the server itself refusing. */
function isUnreachable(error: unknown): boolean {
  return (
    error instanceof NetworkError ||
    (error instanceof ApiError && typeof error.status === "number" && error.status >= 500)
  );
}

/** A launch-time read finished. `source` names which read; `error` is what
 *  it threw, or undefined on success. Only that read's own entry changes
 *  (refinement 11): the notice is up while any read's latest result is
 *  unreachable, and a 4xx or a success clears only the read that made it. */
export function noteReadResult(source: ReadSource, error?: unknown): void {
  if (isUnreachable(error)) failing.add(source);
  else failing.delete(source);
  recompute();
}

/** The read is no longer being made (free runs once a key is saved), so its
 *  last result no longer says anything about the server. Drop it, rather
 *  than let a failure nobody will retry hold the notice up. */
export function forgetReadResult(source: ReadSource): void {
  failing.delete(source);
  recompute();
}

/** Whether this read's latest result was unreachable, so a reconnect
 *  listener can retry exactly the reads that are holding the notice up. */
export function isReadFailing(source: ReadSource): boolean {
  return failing.has(source);
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
