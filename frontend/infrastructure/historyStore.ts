import type { HistoryPatch, HistoryRecord } from "@/domain/entities";
import { StorageUnavailableError } from "@/domain/errors";
import type { HistoryStore } from "@/domain/ports";

/* History lives in this browser, in IndexedDB — not localStorage, because a
   record carries a JPEG Blob and a full analysis (transcripts run to tens of
   KB), and localStorage is a ~5 MB string-only box that blocks the main
   thread. A small hand-written wrapper rather than `idb`: the whole job is one
   object store, one index, get/put/list and a cap, which is less code than the
   dependency's README.

   Opened lazily on first use, never at import time: `container.ts` builds this
   during the static prerender too, where there is no `indexedDB`. */

const DB_NAME = "videolens";
const DB_VERSION = 1;
const STORE = "runs";
const BY_CREATED = "created_at";
const CHANNEL = "videolens-history";

/** How many runs History keeps. Oldest (by `created_at`) goes first. */
export const HISTORY_LIMIT = 20;

const UNAVAILABLE = "This browser is not letting VideoLens keep anything on this device.";

function promisify<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function done(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error ?? new Error("History write aborted"));
  });
}

const EMPTY: Omit<HistoryRecord, "run_id" | "created_at" | "updated_at"> = {
  status: "queued",
  title: null,
  source_kind: null,
  platform: null,
  duration_seconds: null,
  width: null,
  height: null,
  orientation: null,
  summary_snippet: null,
  thumbnail: null,
  result: null,
  source_metadata: null,
  completeness: null,
  error: null,
};

export class IndexedDbHistoryStore implements HistoryStore {
  private dbPromise: Promise<IDBDatabase> | null = null;
  private readonly listeners = new Set<() => void>();
  private channel: BroadcastChannel | null = null;
  private persistAsked = false;

  private open(): Promise<IDBDatabase> {
    if (this.dbPromise) return this.dbPromise;
    this.dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
      let request: IDBOpenDBRequest;
      try {
        if (typeof indexedDB === "undefined") throw new Error("no indexedDB");
        request = indexedDB.open(DB_NAME, DB_VERSION);
      } catch {
        reject(new StorageUnavailableError(UNAVAILABLE));
        return;
      }
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: "run_id" }).createIndex(BY_CREATED, BY_CREATED);
        }
      };
      request.onsuccess = () => {
        const db = request.result;
        /* A newer tab upgrading the schema must not be blocked by this one. */
        db.onversionchange = () => {
          db.close();
          this.dbPromise = null;
        };
        resolve(db);
      };
      request.onerror = () => reject(new StorageUnavailableError(UNAVAILABLE));
      request.onblocked = () => reject(new StorageUnavailableError(UNAVAILABLE));
    });
    /* Remember the refusal: a browser that said no once will say no again,
       and every caller should get the same answer quickly. */
    return this.dbPromise;
  }

  async list(): Promise<HistoryRecord[]> {
    const db = await this.open();
    const tx = db.transaction(STORE, "readonly");
    const records = await promisify(tx.objectStore(STORE).index(BY_CREATED).getAll());
    return (records as HistoryRecord[]).reverse();
  }

  async get(runId: string): Promise<HistoryRecord | null> {
    const db = await this.open();
    const tx = db.transaction(STORE, "readonly");
    const record = await promisify(tx.objectStore(STORE).get(runId));
    return (record as HistoryRecord | undefined) ?? null;
  }

  async upsert(patch: HistoryPatch): Promise<void> {
    const db = await this.open();
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    const now = new Date().toISOString();

    const existing = (await promisify(store.get(patch.run_id))) as HistoryRecord | undefined;
    const merged: HistoryRecord = { ...EMPTY, created_at: now, ...existing, updated_at: now, run_id: patch.run_id };
    for (const [key, value] of Object.entries(patch)) {
      if (value !== undefined) (merged as unknown as Record<string, unknown>)[key] = value;
    }
    store.put(merged);

    /* The cap, inside the same transaction so two tabs writing at once cannot
       both decide they are the 20th. Walk oldest-first and drop the excess. */
    const count = await promisify(store.count());
    let excess = count - HISTORY_LIMIT;
    if (excess > 0) {
      await new Promise<void>((resolve, reject) => {
        const cursorRequest = store.index(BY_CREATED).openCursor();
        cursorRequest.onerror = () => reject(cursorRequest.error);
        cursorRequest.onsuccess = () => {
          const cursor = cursorRequest.result;
          if (!cursor || excess <= 0) return resolve();
          cursor.delete();
          excess -= 1;
          cursor.continue();
        };
      });
    }

    await done(tx);
    this.askToPersist();
    this.notify(true);
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    this.ensureChannel();
    return () => {
      this.listeners.delete(listener);
    };
  }

  /* Without this, Safari may evict the database after 7 days without a visit
     and Chrome under storage pressure. Asked once, the first time History is
     written, never awaited: the answer changes nothing the app does. */
  private askToPersist(): void {
    if (this.persistAsked) return;
    this.persistAsked = true;
    try {
      const storage = typeof navigator !== "undefined" ? navigator.storage : undefined;
      if (storage?.persist) void storage.persist().catch(() => {});
    } catch {
      /* feature missing or refused — fine */
    }
  }

  private ensureChannel(): void {
    if (this.channel || typeof BroadcastChannel === "undefined") return;
    try {
      this.channel = new BroadcastChannel(CHANNEL);
      this.channel.onmessage = () => this.notify(false);
    } catch {
      this.channel = null;
    }
  }

  private notify(broadcast: boolean): void {
    for (const listener of this.listeners) listener();
    if (broadcast) {
      this.ensureChannel();
      try {
        this.channel?.postMessage("changed");
      } catch {
        /* another tab simply won't refresh until it next reads */
      }
    }
  }
}
