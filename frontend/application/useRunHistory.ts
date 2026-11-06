"use client";

import { useCallback, useEffect, useState } from "react";
import type { HistoryRecord, RunPlatform, RunSummary } from "@/domain/entities";
import { knownPlatformName, linkHost, platformFromUrl } from "@/domain/platforms";
import { StorageUnavailableError } from "@/domain/errors";
import { EXPIRED_MESSAGE, bootHistory } from "@/application/historySync";
import { historyStore } from "@/infrastructure/container";

/* History is read from this browser (IndexedDB, via `HistoryStore`), not from
   `GET /api/runs` — the server forgets a run about an hour after it is made,
   so the browser is the only place a run can be listed from after that, and
   it works offline. See docs/frontend/run-history.md.

   Two failure kinds, worded by the hook:
   - `storage`: the browser will not let the app keep anything (some private
     modes). Calm, not red — the app works, History just cannot be saved.
   - `unknown`: a read failed for some other reason; retry re-reads. */

export type RunHistoryErrorKind = "storage" | "unknown";

export type RunHistoryError = { kind: RunHistoryErrorKind; message: string };

/** A History row as the grid draws it: the summary fields plus an object URL
 *  for the stored poster (owned and revoked by this hook). */
export interface HistoryEntry extends RunSummary {
  thumbnail_url: string | null;
  /** Refinement 6 (RUN-13): failed only because the server forgot the run
   *  before its result reached this browser (`EXPIRED_MESSAGE`). Nothing was
   *  wrong with the source, so the row says "Expired", not "Failed". */
  expired: boolean;
}

const STORAGE_MESSAGE = "History can't be saved in this browser.";
const UNKNOWN_MESSAGE = "History could not be read from this browser.";

/* Refinement 9 (item 10): a link run that failed before the server sent any
   metadata (an Instagram download refusal, say) was filed as "Untitled run"
   under a bare "Link" chip — although this browser stored the link it
   submitted. The row now uses what is known, in order: the server's platform
   and title; else the platform judged from the link's host and a title made
   from it ("Instagram link", or the host itself). An upload with no title
   shows its file name. Display only — the record keeps the server's values,
   and real metadata replaces these the moment it arrives. */
function fallbackPlatform(record: HistoryRecord): RunPlatform | null {
  if (record.platform) return record.platform;
  if (record.source_kind === "file") return null;
  return platformFromUrl(record.source_url ?? record.source_metadata?.source_url);
}

function fallbackTitle(record: HistoryRecord, platform: RunPlatform | null): string | null {
  if (record.title?.trim()) return record.title;
  if (record.file_name) return record.file_name;
  const url = record.source_url ?? record.source_metadata?.source_url;
  if (!url) return null;
  const name = knownPlatformName(platform);
  return name ? `${name} link` : linkHost(url);
}

function toEntry(record: HistoryRecord, thumbnailUrl: string | null): HistoryEntry {
  const platform = fallbackPlatform(record);
  return {
    run_id: record.run_id,
    status: record.status,
    title: fallbackTitle(record, platform),
    created_at: record.created_at,
    source_kind: record.source_kind,
    platform,
    duration_seconds: record.duration_seconds,
    summary_snippet: record.summary_snippet,
    orientation: record.orientation,
    width: record.width,
    height: record.height,
    thumbnail_url: thumbnailUrl,
    expired: record.status === "failed" && record.error === EXPIRED_MESSAGE,
  };
}

/** Starts the once-per-load History work (the one-time import from the
 *  server and the re-check of unfinished runs). Mount once, in the shell. */
export function useHistoryBoot(): void {
  useEffect(() => {
    void bootHistory();
  }, []);
}

export function useRunHistory() {
  const [runs, setRuns] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<RunHistoryError | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let sequence = 0;
    /* Object URLs for the posters currently on screen. Replaced wholesale on
       each read and revoked — the Blobs stay in IndexedDB, only the
       in-memory handles are released. */
    let urls: string[] = [];
    const revoke = (list: string[]) => list.forEach((url) => URL.revokeObjectURL(url));

    const load = () => {
      const mine = ++sequence;
      historyStore
        .list()
        .then((records) => {
          if (cancelled || mine !== sequence) return;
          const next: string[] = [];
          const entries = records.map((record) => {
            let url: string | null = null;
            if (record.thumbnail) {
              try {
                url = URL.createObjectURL(record.thumbnail);
                next.push(url);
              } catch {
                url = null;
              }
            }
            return toEntry(record, url);
          });
          const previous = urls;
          urls = next;
          setRuns(entries);
          setError(null);
          /* After the new list is in state, so no frame shows a dead URL. */
          setTimeout(() => revoke(previous), 0);
        })
        .catch((err) => {
          if (cancelled || mine !== sequence) return;
          setError(
            err instanceof StorageUnavailableError
              ? { kind: "storage", message: STORAGE_MESSAGE }
              : { kind: "unknown", message: UNKNOWN_MESSAGE }
          );
        })
        .finally(() => {
          if (!cancelled) setRetrying(false);
        });
    };

    load();
    const unsubscribe = historyStore.subscribe(load);
    return () => {
      cancelled = true;
      unsubscribe();
      revoke(urls);
      urls = [];
    };
  }, [attempt]);

  const retry = useCallback(() => {
    /* Guarded, not disabled: a focused control that becomes `disabled` is
       blurred to <body>, and a keyboard user loses their place. */
    if (retrying) return;
    setRetrying(true);
    setAttempt((n) => n + 1);
  }, [retrying]);

  return { runs, error, retrying, retry };
}
