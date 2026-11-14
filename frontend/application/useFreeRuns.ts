"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";
import type { BillingPlan, FreeRunsPeriod, FreeRunsScope, FreeRunsStatus } from "@/domain/entities";
import { apiKeyStore, freeRunsGateway, nativeShell } from "@/infrastructure/container";
import { BYOK_ATTRIBUTE } from "@/infrastructure/apiKeyStore";
import { forgetReadResult, isReadFailing, noteReadResult, onReconnectChance } from "@/application/serverReachability";

/* Free runs (Phase 5b): an anonymous device gets a few runs per UTC day
   without a Gemini key; a signed-in account gets its own allowance instead
   (2026-11-13; per UTC day on the free plan since 2026-11-14, per month on
   the paid one). This module holds the one copy of what the app knows
   about that allowance, outside React, because three places act on it and
   none of them owns the others:

   - the intake banner (`useFreeRuns`, via HomeScreen) reads it;
   - `useAnalysisRun` refreshes it after a successful submit, marks it spent on
     a 402 `free_runs_used`, and re-reads it to replace the device token on a
     401 `device_token_invalid`;
   - the API key page changes whether it matters at all (a saved key means no
     limit), which arrives through `apiKeyStore.subscribe`.

   Two allowances, one store (2026-11-13). Signed in, the server counts the
   account's runs instead of this device's; the shared
   `ApiClient` adds the bearer, so the same read answers for whoever is
   signed in, and `status.scope` says which allowance it is. Signing in or
   out therefore makes the cached count wrong: `useFreeRuns(identity)` sees
   the change and calls `noteIdentityChanged`, which drops the count and
   reads again under the new identity.

   Quiet by design. A failed or offline status read leaves the banner hidden
   rather than guessing: the server is still the authority, and a 402 on the
   next submit puts the limit state up from the 402's own body. */

type Snapshot = {
  /** The last allowance the server reported (or a 402 implied); `null` while
   *  unknown, after a failed read, or before the first one. */
  status: FreeRunsStatus | null;
  /** A read (or a 402) has answered for the current identity, success or
   *  failure (2026-11-14, Android QA run 22). False on launch and again on a
   *  sign-in or sign-out until the next read lands: the intake keeps the
   *  strip's height reserved meanwhile, so it does not push the page down. */
  settled: boolean;
};

let snapshot: Snapshot = { status: null, settled: false };
const listeners = new Set<() => void>();
let inFlight: Promise<FreeRunsStatus | null> | null = null;
/* Set by a 402 and cleared by the next successful read. While set, a failed
   read keeps the limit state up instead of going quiet: the refusal is hard
   evidence, and hiding it would invite a submit that is certain to fail. */
let refusedSinceLastRead = false;
/* Bumped on every sign-in or sign-out. A read that went out under the old
   identity is not published (its count is someone else's); it is replaced by
   a fresh read instead. */
let identityEpoch = 0;

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
  const epoch = identityEpoch;
  const request: Promise<FreeRunsStatus | null> = freeRunsGateway.fetchStatus().then(
    (status): FreeRunsStatus | Promise<FreeRunsStatus | null> => {
      inFlight = null;
      /* Asked as whoever was signed in before: read again as who is now. */
      if (epoch !== identityEpoch) return refreshFreeRuns();
      noteReadResult("free-runs");
      refusedSinceLastRead = false;
      publish({ status, settled: true });
      return status;
    },
    (err: unknown): null | Promise<FreeRunsStatus | null> => {
      inFlight = null;
      if (epoch !== identityEpoch) return refreshFreeRuns();
      /* Quiet here; whether the server was reachable at all is reported to
         serverReachability, which says so on Analyze (refinement 4). */
      noteReadResult("free-runs", err);
      if (!refusedSinceLastRead) publish({ status: null, settled: true });
      else if (!snapshot.settled) publish({ ...snapshot, settled: true });
      return null;
    }
  );
  inFlight = request;
  return request;
}

/**
 * Someone signed in or out, so the server now counts a different allowance
 * (the account's runs, or this device's). Forgets the
 * cached count, including a 402's limit state (that refusal was for the other
 * identity), and reads again unless a key is saved. Until the read lands the
 * intake shows nothing about free runs, never the other identity's number.
 */
export function noteIdentityChanged(): void {
  identityEpoch += 1;
  refusedSinceLastRead = false;
  publish({ status: null, settled: false });
  if (apiKeyStore.get() === "") void refreshFreeRuns();
}

/**
 * The server refused a run with 402 `free_runs_used`. Puts the limit state up
 * straight away — even when the cached count said runs were left, or when the
 * status read had failed and nothing was known — then confirms with a fresh
 * read (which also learns `resets_at`).
 */
export function markFreeRunsUsed(limit?: number, used?: number, scope?: string): void {
  const prev = snapshot.status;
  const lim = limit ?? prev?.limit ?? 0;
  refusedSinceLastRead = true;
  /* The 402's own scope wins; an older server sends none, so fall back to
     what the last read said, then to this device. */
  const refusedScope: FreeRunsScope =
    scope === "account" || scope === "device" ? scope : (prev?.scope ?? "device");
  publish({
    status: {
      scope: refusedScope,
      /* A 402 is only ever sent to the free plan (a paid account's runs past
         its allowance are billed instead). */
      plan: "free",
      /* Both free allowances count a day (2026-11-14). */
      period: "day",
      overage: false,
      deviceToken: prev?.deviceToken ?? "",
      limit: lim,
      used: used ?? Math.max(lim, prev?.used ?? 0),
      remaining: 0,
      /* A reset instant only means something for the same allowance. */
      resetsAt: prev && prev.scope === refusedScope ? prev.resetsAt : "",
      enabled: true,
    },
    settled: true,
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
  /** `device` (this device) or `account` (the signed-in account). */
  scope: FreeRunsScope;
  /** `day` or `month` (2026-11-14): with the plan, drives the copy. Every
   *  allowance is daily now (device 3, free account 10, paid 30); `month`
   *  only from an older server. */
  period: FreeRunsPeriod;
  /** `paid` (2026-11-13): the paid plan's allowance (30 a day since
   *  2026-11-14), worded as runs rather than free runs. */
  plan: BillingPlan;
  remaining: number;
  limit: number;
  /** None left in this period. On the free plan submits are then blocked
   *  until a key is saved (or, on the device allowance, until someone signs
   *  in); on the paid plan with `overage` they go on, billed per run. */
  exhausted: boolean;
  /** Paid only: runs past the allowance are allowed and billed. */
  overage: boolean;
};

/**
 * What the intake shows about free runs: `null` (show nothing — a key is
 * saved, the deployment has no limit, or the allowance is unknown) or the
 * banner's numbers. `blocked` is true exactly when the limit banner is up.
 *
 * Call once, from the always-mounted shell (`HomeScreen`): it reads the
 * allowance on mount whenever no key is saved, and again whenever the key is
 * removed.
 *
 * `identity` is who is signed in, as the shell knows it: `null` until the
 * sign-in state is known, then the user id or `""` for nobody. A change after
 * the first known value (a sign-in or sign-out) re-reads the allowance under
 * the new identity. The first value does not: the launch read already waits
 * for a stored session before it goes out (`ApiClient`).
 */
export function useFreeRuns(identity: string | null = ""): {
  banner: FreeRunsBanner | null;
  blocked: boolean;
  /** No key is saved and the allowance has not answered yet: the strip may
   *  be about to appear, so the intake reserves its height (2026-11-14,
   *  Android QA run 22: the late strip pushed the page down ~93px at 412). */
  pending: boolean;
} {
  const { status, settled } = useSyncExternalStore(subscribe, () => snapshot, () => snapshot);
  const hasKey = useSyncExternalStore(subscribeKey, hasKeySnapshot, hasKeyServerSnapshot);

  /* Keep the pre-paint `data-byok` stamp in step with the key, so the CSS
     that drops the reserved strip height follows a key saved or removed
     later. Not on the first (hydration) render, which always reads "no key"
     and would wipe a correct stamp a frame before the real value lands. */
  const sawKey = useRef(false);
  useEffect(() => {
    if (hasKey) {
      sawKey.current = true;
      document.documentElement.setAttribute(BYOK_ATTRIBUTE, "");
    } else if (sawKey.current) {
      document.documentElement.removeAttribute(BYOK_ATTRIBUTE);
    }
  }, [hasKey]);

  const knownIdentity = useRef<string | null>(null);
  useEffect(() => {
    if (identity === null) return;
    const previous = knownIdentity.current;
    knownIdentity.current = identity;
    if (previous !== null && previous !== identity) noteIdentityChanged();
  }, [identity]);

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

  /* Spent for this period: read again just after the UTC reset the server
     named, so a tab left open overnight unblocks itself. Capped at a day, so
     a bogus far-future instant cannot overflow setTimeout (and a paid
     month-end reset is simply checked once a day until it is near). */
  const resetsAt = status && status.remaining <= 0 ? status.resetsAt : "";
  useEffect(() => {
    if (hasKey || !resetsAt) return;
    const due = Date.parse(resetsAt);
    if (Number.isNaN(due)) return;
    const wait = Math.min(Math.max(due - Date.now(), 0) + 2000, 24 * 60 * 60 * 1000);
    const timer = setTimeout(() => void refreshFreeRuns(), wait);
    return () => clearTimeout(timer);
  }, [hasKey, resetsAt]);

  if (hasKey || !status || !status.enabled) return { banner: null, blocked: false, pending: !hasKey && !settled };
  const exhausted = status.remaining <= 0;
  const overage = status.plan === "paid" && status.overage;
  return {
    banner: {
      scope: status.scope,
      plan: status.plan,
      period: status.period,
      remaining: Math.max(0, status.remaining),
      limit: status.limit,
      exhausted,
      overage,
    },
    /* Paid with overage: the allowance running out costs money per run, it
       does not stop anyone (the server sends no 402 then). */
    blocked: exhausted && !overage,
    pending: false,
  };
}
