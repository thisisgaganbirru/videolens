"use client";

import { useCallback, useRef, useState, useSyncExternalStore } from "react";
import { ApiError, NetworkError } from "@/domain/errors";
import { refreshBilling } from "@/application/useBilling";
import { revalidateFreeRuns } from "@/application/useFreeRuns";
import { accountGateway, accountHoldSource } from "@/infrastructure/container";

/* The 30-day account deletion hold (2026-11-14, docs/frontend/saved-history.md).

   A deleted account is held, not removed: signing in again with the same
   email is answered 410 `account_pending_deletion` (with `purge_at`) on every
   route that resolves who is calling. The API client hears every one of
   them, whichever gateway asked, and this module keeps the last one, keyed
   by the identity the request went out as (`user:<id>`), so a sign-out or a
   different person never inherits it. The Account tab shows the restore
   state while the signed-in person is held; History and the result line
   fall back to what this browser keeps.

   Restoring (`POST /api/me/restore`) clears it and asks for the plan and the
   run allowance again; whoever else reads the account (useAccount, saved
   history) re-reads on `restoredEpoch`. */

export type AccountHold = { purgeAt: string | null };

type Snapshot = {
  /** `user:<id>` → the hold heard for that identity. */
  holds: ReadonlyMap<string, AccountHold>;
  /** Bumped by each successful restore, so readers keyed on it re-read. */
  restoredEpoch: number;
};

let snapshot: Snapshot = { holds: new Map(), restoredEpoch: 0 };
const listeners = new Set<() => void>();

function publish(next: Partial<Snapshot>) {
  snapshot = { ...snapshot, ...next };
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const getSnapshot = () => snapshot;
const SERVER_SNAPSHOT: Snapshot = { holds: new Map(), restoredEpoch: 0 };
const getServerSnapshot = () => SERVER_SNAPSHOT;

if (typeof window !== "undefined") {
  accountHoldSource.subscribe(({ owner, purgeAt }) => {
    if (!owner?.startsWith("user:")) return;
    const known = snapshot.holds.get(owner);
    if (known && known.purgeAt === purgeAt) return;
    const holds = new Map(snapshot.holds);
    holds.set(owner, { purgeAt: purgeAt ?? known?.purgeAt ?? null });
    publish({ holds });
  });
}

function clearHold(userId: string): void {
  const key = `user:${userId}`;
  if (!snapshot.holds.has(key)) return;
  const holds = new Map(snapshot.holds);
  holds.delete(key);
  publish({ holds });
}

/** The hold the server reported for this signed-in person, or null. */
export function useAccountHold(userId: string | null): AccountHold | null {
  const current = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return userId ? (current.holds.get(`user:${userId}`) ?? null) : null;
}

/** Bumped after every successful restore; key a re-read on it. */
export function useRestoredEpoch(): number {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot).restoredEpoch;
}

export type RestoreState =
  | { phase: "idle" }
  | { phase: "restoring" }
  | { phase: "restored" }
  | { phase: "closed" }
  | { phase: "failed"; message: string };

const RESTORE_FAILED = "Your account could not be restored just now. Try again in a moment.";
const RESTORE_UNREACHABLE = "Could not reach VideoLens to restore your account. Check your connection and try again.";

/** `POST /api/me/restore` for the signed-in, held person. `closed` is the
 *  410 `restore_window_closed`: the 30 days have passed. */
export function useAccountRestore(userId: string | null) {
  const [state, setState] = useState<RestoreState>({ phase: "idle" });
  const inFlight = useRef(false);

  const restore = useCallback(async () => {
    if (!userId || inFlight.current) return;
    inFlight.current = true;
    setState({ phase: "restoring" });
    try {
      await accountGateway.restoreAccount();
    } catch (err: unknown) {
      inFlight.current = false;
      if (err instanceof ApiError && err.code === "restore_window_closed") {
        setState({ phase: "closed" });
      } else {
        setState({ phase: "failed", message: err instanceof NetworkError ? RESTORE_UNREACHABLE : RESTORE_FAILED });
      }
      return;
    }
    /* Restored (or it was not held after all, which ends the same way):
       nothing is refused any more, so everything that read the account
       while it was held reads it again. */
    inFlight.current = false;
    setState({ phase: "restored" });
    clearHold(userId);
    publish({ restoredEpoch: snapshot.restoredEpoch + 1 });
    void refreshBilling();
    void revalidateFreeRuns();
  }, [userId]);

  return { state, restore };
}
