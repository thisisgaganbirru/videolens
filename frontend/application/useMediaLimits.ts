"use client";

import { useEffect, useSyncExternalStore } from "react";
import type { MediaLimits, MediaLimitsTable } from "@/domain/entities";
import { apiKeyStore, limitsGateway } from "@/infrastructure/container";

/* Upload limits (owner decision 2026-11-13, "Level 2"): a signed-in person
   running on their own Gemini key may send longer and larger media than
   everyone else. The server owns the numbers (`GET /api/limits`) and enforces
   them; the intake reads them only to word its hint and to refuse a file
   before uploading it.

   One read per app load, kept outside React like the free-run count, so
   every consumer shares it. Until it lands, and for good when it fails (a
   server from before the endpoint answers 404), the table is today's
   standard limits for BOTH tiers: an older server refuses anything longer,
   so advertising the larger tier there would be a promise it cannot keep. */

const STANDARD: MediaLimits = { maxDurationSeconds: 180, maxFileSizeMb: 200 };
export const FALLBACK_LIMITS: MediaLimitsTable = { standard: STANDARD, signedInByok: STANDARD, paid: null };

let table: MediaLimitsTable = FALLBACK_LIMITS;
let requested = false;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function load(): void {
  if (requested) return;
  requested = true;
  limitsGateway.fetchLimits().then(
    (next) => {
      table = next;
      listeners.forEach((listener) => listener());
    },
    () => {
      /* Quiet: the fallback is already in place, and the server re-checks
         every upload. Reachability is reported by the other launch reads. */
    }
  );
}

const subscribeKey = (listener: () => void) => apiKeyStore.subscribe(listener);
const hasKeySnapshot = () => apiKeyStore.get() !== "";
/* Prerendered with no key; React re-renders with the real value after
   hydration, so nothing reads localStorage during render. */
const hasKeyServerSnapshot = () => false;

export type MediaLimitsState = {
  /** The limits that apply to this person right now. */
  limits: MediaLimits;
  /** A larger tier is in effect (the paid plan, or signed in with a key). */
  extended: boolean;
  /** Minutes the paid plan allows, for the Plan group's pitch (10 at
   *  launch); null until the server has reported a paid tier, so the pitch
   *  never quotes a number it has not heard. */
  paidMinutes: number | null;
  /** Minutes the larger tier would allow, when it is actually larger than
   *  what applies now; null when there is nothing more to offer (already
   *  extended, or the server reports no larger tier). Drives the quiet
   *  "Sign in for videos up to N minutes." hint. */
  upgradeMinutes: number | null;
  /** A key is saved on this device. */
  hasKey: boolean;
};

/**
 * The upload limits for whoever is using the app. `signedIn` comes from the
 * shell (`useAuthUser`), which already holds the sign-in state; the saved key
 * is watched here. Either changing recomputes the result.
 *
 * Call from the always-mounted shell (`HomeScreen`), like `useCapabilities`.
 */
export function useMediaLimits(signedIn: boolean, paid = false): MediaLimitsState {
  const current = useSyncExternalStore(subscribe, () => table, () => FALLBACK_LIMITS);
  const hasKey = useSyncExternalStore(subscribeKey, hasKeySnapshot, hasKeyServerSnapshot);

  useEffect(() => {
    load();
  }, []);

  /* Paid plan first (2026-11-13), then signed in with a key, then standard.
     A server that sends no `paid` tier leaves the paid plan on the rules
     below it, so the intake never promises what that server would refuse. */
  const paidTier = signedIn && paid ? current.paid : null;
  const byok = signedIn && hasKey;
  const limits = paidTier ?? (byok ? current.signedInByok : current.standard);
  const extended = paidTier !== null || byok;
  const larger = current.signedInByok.maxDurationSeconds > current.standard.maxDurationSeconds;
  return {
    limits,
    extended,
    upgradeMinutes: !extended && larger ? Math.floor(current.signedInByok.maxDurationSeconds / 60) : null,
    paidMinutes: current.paid ? Math.floor(current.paid.maxDurationSeconds / 60) : null,
    hasKey,
  };
}

/** "3 minutes", "10 minutes", "90 seconds": a limit as the intake says it. */
export function durationLabel(seconds: number): string {
  if (seconds % 60 === 0) {
    const minutes = seconds / 60;
    return minutes === 1 ? "1 minute" : `${minutes} minutes`;
  }
  return `${Math.round(seconds)} seconds`;
}
