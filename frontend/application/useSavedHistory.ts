"use client";

import { useEffect, useSyncExternalStore } from "react";
import type { SavedHistoryStatus, SavedRunSummary } from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import { savedHistoryGateway } from "@/infrastructure/container";
import { useRestoredEpoch } from "@/application/accountHold";

/* Paid saved history (2026-11-14, docs/frontend/saved-history.md).

   A paid account's successful runs are saved on the server; this is the one
   copy of that list, outside React like the plan (useBilling), because the
   History tab, the result line, the Analyze card's retention line and the
   Account page all read whether this account is saving. HomeScreen, which
   never unmounts, says who is signed in.

   Quiet by design. Nothing is asked unless someone is signed in where
   sign-in works. An older backend (404), a refused caller (401/403) or a
   failed first read with no reason to think the account is paid all read as
   "off": the browser's own History, exactly as before. A held account (410)
   is "held". The first page is re-read when the History tab opens and after
   a run finishes; "Load more" appends the next page by its cursor. */

/** How History should present the account:
 *  - `off`: nothing on the server for this person (free, anonymous, an
 *    older backend, sign-in off). Today's browser-only page.
 *  - `pending`: signed in, the first read has not answered yet.
 *  - `saving`: paid, every successful run is saved.
 *  - `window`: the plan ended; saved runs stay until `expires_at`.
 *  - `failed`: the first read failed for an account believed to be paid.
 *  - `held`: the account is in the 30-day deletion hold. */
export type SavedHistoryMode = "off" | "pending" | "saving" | "window" | "failed" | "held";

export const SAVED_PAGE_SIZE = 20;

type Snapshot = {
  owner: string | null;
  status: SavedHistoryStatus | null;
  items: SavedRunSummary[];
  nextCursor: string | null;
  /** The first read for `owner` answered, one way or the other. */
  settled: boolean;
  /** The last first-page read failed (a later one may recover). */
  failed: boolean;
  /** 404/401/403: this server has no saved history for this caller. */
  unsupported: boolean;
  held: boolean;
  /** A first-page re-read is on the wire (the list stays on screen). */
  refreshing: boolean;
  loadingMore: boolean;
  loadMoreFailed: boolean;
};

const EMPTY: Snapshot = {
  owner: null,
  status: null,
  items: [],
  nextCursor: null,
  settled: false,
  failed: false,
  unsupported: false,
  held: false,
  refreshing: false,
  loadingMore: false,
  loadMoreFailed: false,
};

let snapshot: Snapshot = EMPTY;
const listeners = new Set<() => void>();
let owner: string | null = null;
let epoch = 0;
let firstPage: Promise<void> | null = null;

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
const getServerSnapshot = () => EMPTY;

function refusal(err: unknown): Partial<Snapshot> {
  if (err instanceof ApiError && err.status === 410) return { held: true, failed: false, unsupported: false };
  if (err instanceof ApiError && (err.status === 404 || err.status === 401 || err.status === 403 || err.status === 405)) {
    return { unsupported: true, failed: false, held: false };
  }
  return { failed: true };
}

/** Re-read the first page for whoever is signed in. Shares an in-flight
 *  read; the list on screen stays until the answer replaces it. */
export function refreshSavedHistory(): Promise<void> {
  if (!owner) return Promise.resolve();
  if (firstPage) return firstPage;
  const asked = epoch;
  publish({ refreshing: true });
  firstPage = savedHistoryGateway.list(SAVED_PAGE_SIZE, null).then(
    (page) => {
      firstPage = null;
      if (asked !== epoch) return;
      publish({
        status: { saving: page.saving, expires_at: page.expires_at },
        items: page.items,
        nextCursor: page.next_cursor,
        settled: true,
        failed: false,
        unsupported: false,
        held: false,
        refreshing: false,
        loadMoreFailed: false,
      });
    },
    (err: unknown) => {
      firstPage = null;
      if (asked !== epoch) return;
      publish({ settled: true, refreshing: false, ...refusal(err) });
    }
  );
  return firstPage;
}

/** Appends the next page. A failure leaves the list and offers a retry. */
export async function loadMoreSaved(): Promise<void> {
  const cursor = snapshot.nextCursor;
  if (!owner || !cursor || snapshot.loadingMore) return;
  const asked = epoch;
  publish({ loadingMore: true, loadMoreFailed: false });
  try {
    const page = await savedHistoryGateway.list(SAVED_PAGE_SIZE, cursor);
    if (asked !== epoch) return;
    const seen = new Set(snapshot.items.map((item) => item.run_id));
    publish({
      status: { saving: page.saving, expires_at: page.expires_at },
      items: [...snapshot.items, ...page.items.filter((item) => !seen.has(item.run_id))],
      nextCursor: page.next_cursor,
      loadingMore: false,
    });
  } catch (err: unknown) {
    if (asked !== epoch) return;
    publish({ loadingMore: false, loadMoreFailed: true, ...(err instanceof ApiError && err.status === 410 ? { held: true } : {}) });
  }
}

/* Runs found gone while History was on its way out (a 404 on opening one).
   Not published: the list still on screen must not drop the card under the
   person's finger. Left out of whatever History renders next. */
const gone = new Set<string>();

/** Marks a run as gone without redrawing the list now (see `gone`). */
export function markSavedRunGone(runId: string): void {
  gone.add(runId);
}

/** The runs marked gone so far; History reads it once, when it mounts. */
export function goneSavedRuns(): ReadonlySet<string> {
  return new Set(gone);
}

/** Drops one run from the list without asking. */
export function forgetSavedRun(runId: string): void {
  if (!snapshot.items.some((item) => item.run_id === runId)) return;
  publish({ items: snapshot.items.filter((item) => item.run_id !== runId) });
}

/** `DELETE /api/history/{run_id}`. A 404 means it is already gone, which is
 *  what was asked for. Rejects with the gateway's error otherwise. */
export async function deleteSavedRun(runId: string): Promise<void> {
  try {
    await savedHistoryGateway.remove(runId);
  } catch (err: unknown) {
    if (!(err instanceof ApiError && err.status === 404)) throw err;
  }
  forgetSavedRun(runId);
}

/** `DELETE /api/history`: every saved run of the account. */
export async function deleteAllSavedRuns(): Promise<void> {
  await savedHistoryGateway.removeAll();
  epoch += 1;
  firstPage = null;
  publish({ items: [], nextCursor: null, loadingMore: false, loadMoreFailed: false });
  void refreshSavedHistory();
}

function setOwner(next: string | null): void {
  if (next === owner) return;
  owner = next;
  epoch += 1;
  firstPage = null;
  publish({ ...EMPTY, owner: next });
  if (next) void refreshSavedHistory();
}

function modeOf(current: Snapshot, paidHint: boolean): SavedHistoryMode {
  if (!current.owner) return "off";
  if (current.held) return "held";
  if (!current.settled) return "pending";
  if (current.unsupported) return "off";
  if (current.status?.saving) return "saving";
  if (current.status?.expires_at) return "window";
  if (current.failed && current.status === null) return paidHint ? "failed" : "off";
  return "off";
}

export type SavedHistoryState = Snapshot & { mode: SavedHistoryMode };

/**
 * The signed-in account's saved runs, for the shell. `userId` is who is
 * signed in (null for nobody or not known yet); `enabled` is whether sign-in
 * works on this server. `paidHint` (the plan or the run count says paid)
 * decides whether a failed first read is shown as a failure or quietly as
 * the browser-only page. A restore re-reads (useRestoredEpoch).
 */
export function useSavedHistory(userId: string | null, enabled: boolean, paidHint: boolean): SavedHistoryState {
  const restoredEpoch = useRestoredEpoch();
  const target = enabled ? userId : null;
  useEffect(() => {
    setOwner(target);
  }, [target]);
  useEffect(() => {
    if (restoredEpoch > 0) void refreshSavedHistory();
  }, [restoredEpoch]);
  const current = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  /* Until the effect above has run for a new person, the snapshot is the
     previous one's: never show it for someone else. */
  const mine = current.owner === target ? current : { ...EMPTY, owner: target };
  return { ...mine, mode: modeOf(mine, paidHint) };
}
