"use client";

import { useEffect, useSyncExternalStore } from "react";
import type { FreeRunsStatus } from "@/domain/entities";
import { apiKeyStore, freeRunsGateway, nativeShell } from "@/infrastructure/container";
import { forgetReadResult, isReadFailing, noteReadResult, onReconnectChance } from "@/application/serverReachability";

/* Free runs (Phase 5b): an anonymous device gets a few runs per UTC day
   without a Gemini key. This module holds the one copy of what the app knows
   about that allowance, outside React, because three places act on it and
   none of them owns the others:

   - the intake banner (`useFreeRuns`, via HomeScreen) reads it;
   - `useAnalysisRun` refreshes it after a successful submit, marks it spent on
     a 402 `free_runs_used`, and re-reads it to replace the device token on a
     401 `device_token_invalid`;
   - the API key page changes whether it matters at all (a saved key means no
     limit), which arrives through `apiKeyStore.subscribe`.

   Quiet by design. A failed or offline status read leaves the banner hidden
   rather than guessing: the server is still the authority, and a 402 on the
   next submit puts the limit state up from the 402's own body. */

type Snapshot = {
  /** The last allowance the server reported (or a 402 implied); `null` while
   *  unknown, after a failed read, or before the first one. */
  status: FreeRunsStatus | null;
};

let snapshot: Snapshot = { status: null };
const listeners = new Set<() => void>();
let inFlight: Promise<FreeRunsStatus | null> | null = null;
/* Set by a 402 and cleared by the next successful read. While set, a failed
   read keeps the limit state up instead of going quiet: the refusal is hard
   evidence, and hiding it would invite a submit that is certain to fail. */
let refusedSinceLastRead = false;

function publish(next: Snapshot) {
  snapshot = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Re-read this device's allowance from the server. Concurrent callers share
 * one request. Resolves with the new status, or `null` when the read failed —
 * never rejects, so callers never need a try around it. A failure clears the
 * known status (banner goes quiet) rather than leaving a stale count up.
 *
 * Also the way to replace an invalid device token: the adapter stores
 * whatever token the server answers with.
 */
export function refreshFreeRuns(): Promise<FreeRunsStatus | null> {
  if (inFlight) return inFlight;
  inFlight = freeRunsGateway
    .fetchStatus()
    .then((status) => {
      noteReadResult("free-runs");
      refusedSinceLastRead = false;
      publish({ status });
      return status;
    })
    .catch((err: unknown) => {
      /* Quiet here; whether the server was reachable at all is reported to
         serverReachability, which says so on Analyze (refinement 4). */
      noteReadResult("free-runs", err);
      if (!refusedSinceLastRead) publish({ status: null });
      return null;
    })
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

/**
 * The server refused a run with 402 `free_runs_used`. Puts the limit state up
 * straight away — even when the cached count said runs were left, or when the
 * status read had failed and nothing was known — then confirms with a fresh
 * read (which also learns `resets_at`).
 */
export function markFreeRunsUsed(limit?: number, used?: number): void {
  const prev = snapshot.status;
  const lim = limit ?? prev?.limit ?? 0;
  refusedSinceLastRead = true;
  publish({
    status: {
      deviceToken: prev?.deviceToken ?? "",
      limit: lim,
      used: used ?? Math.max(lim, prev?.used ?? 0),
      remaining: 0,
      resetsAt: prev?.resetsAt ?? "",
      enabled: true,
    },
  });
  void refreshFreeRuns();
}

/** A run was accepted: one fewer free run, unless it ran on the user's own
 *  key (which the server does not count). */
export function noteRunAccepted(): void {
  if (apiKeyStore.get() === "") void refreshFreeRuns();
}

/** The allowance as last read, or null when unknown. `useAnalysisRun` takes
 *  this just before a submit, so a failed run can later be compared against
 *  it (refinement 9, the refund line). */
export function currentFreeRuns(): FreeRunsStatus | null {
  return snapshot.status;
}

/** Whether runs are on the user's own key right now (no free-run accounting
 *  applies, and nothing about free runs is ever said). */
export function usingOwnKey(): boolean {
  return apiKeyStore.get() !== "";
}

/**
 * Refinement 9: read the allowance again because something may have changed
 * it behind the cached count — a run settled (a failed link download is
 * refunded server-side), the intake came back on screen, or the app returned
 * from the background (the counter resets at UTC midnight while the app can
 * stay open). A no-op on the user's own key. Resolves with the fresh status
 * (or null), never rejects.
 */
export function revalidateFreeRuns(): Promise<FreeRunsStatus | null> {
  if (usingOwnKey()) return Promise.resolve(null);
  return refreshFreeRuns();
}

const subscribeKey =(listener: () => void) => apiKeyStore.subscribe(listener);
const hasKeySnapshot = () => apiKeyStore.get() !== "";
/* The prerendered HTML is built with no key; the first client render agrees,
   and React re-renders with the real value right after hydration. */
const hasKeyServerSnapshot = () => false;

export type FreeRunsBanner = {
  remaining: number;
  limit: number;
  /** No free runs left today: submits are blocked until a key is saved. */
  exhausted: boolean;
};

/**
 * What the intake shows about free runs: `null` (show nothing — a key is
 * saved, the deployment has no limit, or the allowance is unknown) or the
 * banner's numbers. `blocked` is true exactly when the limit banner is up.
 *
 * Call once, from the always-mounted shell (`HomeScreen`): it reads the
 * allowance on mount whenever no key is saved, and again whenever the key is
 * removed.
 */
export function useFreeRuns(): { banner: FreeRunsBanner | null; blocked: boolean } {
  const { status } = useSyncExternalStore(subscribe, () => snapshot, () => snapshot);
  const hasKey = useSyncExternalStore(subscribeKey, hasKeySnapshot, hasKeyServerSnapshot);

  useEffect(() => {
    if (hasKey) {
      /* No read is made on a saved key, so a failure from before the key
         was saved must not keep the "can't reach" notice up (refinement
         11): nothing would ever retry it. */
      forgetReadResult("free-runs");
      return;
    }
    void refreshFreeRuns();
    /* The launch read failed for want of a connection: read again when it
       may be back (refinement 4, LCH-06), so the pill appears on its own.
       Refinement 11: also whenever this read is the one holding the notice
       up. After a 402 the status is kept, so `null` alone would miss it. */
    return onReconnectChance(() => {
      if (snapshot.status === null || isReadFailing("free-runs")) void refreshFreeRuns();
    });
  }, [hasKey]);

  /* Refinement 9: the count only used to refresh on a cold launch, so a
     phone that kept the app open past the UTC reset (or got a refund) showed
     a stale number. Read again whenever the app comes back: the page becoming
     visible (browsers, and the Android WebView), and Capacitor's own `resume`
     event on the native shell. The two often fire together; one read, not
     two (refreshFreeRuns also shares an in-flight request). */
  useEffect(() => {
    if (hasKey) return;
    let last = 0;
    const again = () => {
      const now = Date.now();
      if (now - last < 1500) return;
      last = now;
      void refreshFreeRuns();
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") again();
    };
    document.addEventListener("visibilitychange", onVisible);
    const offResume = nativeShell.onResume(again);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      offResume();
    };
  }, [hasKey]);

  /* Spent for today: read again just after the UTC reset the server named, so
     a tab left open overnight unblocks itself. Capped so a bogus far-future
     instant cannot overflow setTimeout. */
  const resetsAt = status && status.remaining <= 0 ? status.resetsAt : "";
  useEffect(() => {
    if (hasKey || !resetsAt) return;
    const due = Date.parse(resetsAt);
    if (Number.isNaN(due)) return;
    const wait = Math.min(Math.max(due - Date.now(), 0) + 2000, 24 * 60 * 60 * 1000);
    const timer = setTimeout(() => void refreshFreeRuns(), wait);
    return () => clearTimeout(timer);
  }, [hasKey, resetsAt]);

  if (hasKey || !status || !status.enabled) return { banner: null, blocked: false };
  const exhausted = status.remaining <= 0;
  return {
    banner: { remaining: Math.max(0, status.remaining), limit: status.limit, exhausted },
    blocked: exhausted,
  };
}
