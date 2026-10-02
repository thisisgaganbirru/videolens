"use client";

import { ArrowRight, Search } from "lucide-react";
import { useLibrary } from "@/application/useLibrary";
import type { LibraryEntry } from "@/domain/entities";
import { formatDate } from "@/components/format";

/* Search over everything the caller has analyzed.

   Same panel for every deployment. What differs is the reach, and the backend
   decides it: an anonymous caller (or a deployment without durable storage)
   searches titles and text over their recent history; a workspace with
   storage searches every run it has ever completed. The panel never says
   which — a caller with twelve runs gets the same twelve either way. */

const PLATFORMS = ["YouTube", "Instagram", "TikTok", "Facebook", "Twitter", "Upload"] as const;

function durationLabel(seconds: number | null): string {
  if (seconds == null) return "";
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return minutes ? `${minutes}m ${rest.toString().padStart(2, "0")}s` : `${rest}s`;
}

function Row({ entry, onOpen }: { entry: LibraryEntry; onOpen: () => void }) {
  const fallback = entry.status === "failed" ? "Failed run" : "Untitled run";
  const meta = [entry.platform, durationLabel(entry.duration_seconds), formatDate(entry.created_at)]
    .filter(Boolean)
    .join(" · ");
  return (
    <li>
      <button type="button" onClick={onOpen} className="history-row library-row min-h-12" data-run-status={entry.status}>
        <span className="h-left">
          <span className="h-dot" aria-hidden="true" />
          <span className="h-text">
            <span className="h-title" data-fallback={entry.title ? undefined : ""}>
              {entry.title || fallback}
            </span>
            {entry.summary && <span className="library-summary">{entry.summary}</span>}
            <span className="h-sub">{meta}</span>
          </span>
        </span>
        <span className="h-right">
          <ArrowRight className="h-go" aria-hidden="true" />
        </span>
      </button>
    </li>
  );
}

export default function LibraryPanel({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const { query, search, platform, filterPlatform, page, setPage, runs, error, loading, retry, hasMore } =
    useLibrary();

  return (
    <div className="library">
      <div className="library-controls">
        <label className="library-search">
          <Search aria-hidden="true" />
          <span className="sr-only">Search your library</span>
          <input
            type="search"
            className="field"
            value={query}
            onChange={(event) => search(event.target.value)}
            placeholder="search titles, transcripts, on-screen text"
            autoComplete="off"
          />
        </label>
        <div className="library-filters" role="group" aria-label="Platform">
          <button
            type="button"
            className="chip"
            aria-pressed={platform === null}
            onClick={() => filterPlatform(null)}
          >
            all
          </button>
          {PLATFORMS.map((name) => (
            <button
              key={name}
              type="button"
              className="chip"
              aria-pressed={platform === name}
              onClick={() => filterPlatform(platform === name ? null : name)}
            >
              {name.toLowerCase()}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <div role="alert" className="error-inline">
          <p>{error.message}</p>
          <button type="button" onClick={retry} className="btn btn-secondary">
            Try again
          </button>
        </div>
      ) : runs === null ? (
        <p role="status" className="pending-note">
          Loading…
        </p>
      ) : runs.length === 0 ? (
        <p className="pending-note">
          {query || platform ? "Nothing matches." : "Nothing analyzed yet."}
        </p>
      ) : (
        <ul className="history-list" aria-busy={loading || undefined}>
          {runs.map((entry) => (
            <Row key={entry.run_id} entry={entry} onOpen={() => onOpenRun(entry.run_id)} />
          ))}
        </ul>
      )}

      {(page > 0 || hasMore) && (
        <div className="apikey-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setPage(page - 1)}
            aria-disabled={page === 0 || undefined}
          >
            newer
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setPage(page + 1)}
            aria-disabled={!hasMore || undefined}
          >
            older
          </button>
        </div>
      )}
    </div>
  );
}
