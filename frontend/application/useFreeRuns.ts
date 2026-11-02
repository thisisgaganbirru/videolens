"use client";

import { useEffect, useSyncExternalStore } from "react";
import type { FreeRunsStatus } from "@/domain/entities";
import { apiKeyStore, freeRunsGateway } from "@/infrastructure/container";

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
      refusedSinceLastRead = false;
      publish({ status });
      return status;
    })
    .catch(() => {
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
    if (!hasKey) void refreshFreeRuns();
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
