"use client";

import { useId, useMemo, useState } from "react";
import { AudioLines, ChevronDown, Play } from "lucide-react";
import { useRunHistory } from "@/application/useRunHistory";
import type { RunSourceKind, RunSummary } from "@/domain/entities";
import {
  HISTORY_FILTERS,
  buildHistory,
  isAudio,
  isLandscape,
  platformLabel,
  posterBadge,
  posterDate,
  posterLabel,
  posterTint,
  posterTitle,
  type HistoryFilter,
  type HistorySort,
} from "@/components/history";
import { useMediaQuery } from "@/components/useMediaQuery";

/** Where the sort control appears — the same 48rem the controls row turns at
 *  in globals.css (HISTORY block). Keep the two in step. */
const SORT_QUERY = "(min-width: 48rem)";

/* History — a poster grid (design/shots/HistoryA*.png, HistoryMobile.png,
   HistoryWeb.png). Everything that decides *what* shows lives in the pure
   components/history.ts; this file only renders. Filtering, search and sort
   are client-side over the <=20 runs the backend returns — there is no paging
   to coordinate with. */

interface HistoryPanelProps {
  onOpenRun: (runId: string, sourceKind?: RunSourceKind | null) => void;
  /** Leaves History for the intake — the empty state's one action. */
  onAnalyze: () => void;
}

export default function HistoryPanel({ onOpenRun, onAnalyze }: HistoryPanelProps) {
  const { runs, error, retrying, retry } = useRunHistory();

  return (
    <div className="history">
      <header className="history-head">
        <h1 className="history-title">History</h1>
        <p className="history-lede">Your recent analyses. Open one to read its notes again.</p>
      </header>
      <HistoryBody
        runs={runs}
        error={error}
        retrying={retrying}
        retry={retry}
        onOpenRun={onOpenRun}
        onAnalyze={onAnalyze}
      />
    </div>
  );
}

function HistoryBody({
  runs,
  error,
  retrying,
  retry,
  onOpenRun,
  onAnalyze,
}: ReturnType<typeof useRunHistory> & HistoryPanelProps) {
  /* .error-inline, not .error-block: one condition inside a view, not the
     whole app having failed. The wording is the hook's — a server that
     answered gets its own `detail`, one that never answered gets told so —
     and is never overwritten here. */
  if (error)
    return (
      <div role="alert" className="error-inline history-state">
        <p>{error.message}</p>
        <button
          type="button"
          onClick={retry}
          className="btn btn-secondary"
          aria-disabled={retrying || undefined}
        >
          {retrying ? "Retrying…" : "Try again"}
        </button>
      </div>
    );
  if (runs === null)
    return (
      <p role="status" className="pending-note history-state">
        Loading your runs…
      </p>
    );
  /* A 200 with {"runs": []} — nothing has been analyzed in this browser yet.
     Not an error, so no red and no retry: one way forward instead. */
  if (runs.length === 0)
    return (
      <div className="history-empty">
        <p className="history-empty-title">No runs yet.</p>
        <p className="history-empty-body">
          Analyze a link or a file and it will wait here, so you can read its notes again later.
        </p>
        <button type="button" className="btn btn-secondary" onClick={onAnalyze}>
          Analyze a video
        </button>
      </div>
    );

  return <HistoryGrid runs={runs} onOpenRun={onOpenRun} />;
}

function HistoryGrid({
  runs,
  onOpenRun,
}: {
  runs: RunSummary[];
  onOpenRun: HistoryPanelProps["onOpenRun"];
}) {
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<HistorySort>("newest");
  const searchId = useId();
  const sortId = useId();

  /* The sort control exists only from 48rem (the phone boards draw search on
     its own full-width row and no sort). Below that it is display:none, and
     the order is always Newest: a choice the user can no longer see must not
     go on shaping the list. The desktop choice is kept, not reset, so widening
     the window again brings it back exactly as it was left. */
  const sortVisible = useMediaQuery(SORT_QUERY);
  const effectiveSort: HistorySort = sortVisible ? sort : "newest";

  /* "Today" is fixed for the life of this list rather than read on every
     keystroke, so a run cannot hop groups mid-search at midnight. A fresh
     visit to the tab remounts and reads it again. */
  const now = useMemo(() => new Date(), []);
  const groups = useMemo(
    () => buildHistory(runs, { filter, query, sort: effectiveSort, now }),
    [runs, filter, query, effectiveSort, now]
  );
  const shown = groups.reduce((n, group) => n + group.runs.length, 0);
  const narrowed = filter !== "all" || query.trim() !== "";

  const clear = () => {
    setFilter("all");
    setQuery("");
  };

  return (
    <>
      <div className="history-controls">
        <div className="history-filters" role="group" aria-label="Show runs from">
          {HISTORY_FILTERS.map((option) => (
            <button
              key={option.id}
              type="button"
              className="filter-pill"
              aria-pressed={filter === option.id}
              onClick={() => setFilter(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="history-search">
          <label htmlFor={searchId} className="sr-only">
            Search your runs
          </label>
          <input
            id={searchId}
            type="search"
            className="field field-pill"
            placeholder="Search your runs"
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="history-sort">
          <label htmlFor={sortId} className="sr-only">
            Sort
          </label>
          <select
            id={sortId}
            className="sort-select"
            value={sort}
            onChange={(event) => setSort(event.target.value as HistorySort)}
          >
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
          </select>
          <ChevronDown className="sort-chevron" aria-hidden="true" />
        </div>
      </div>

      {/* Announces the count only once something has narrowed the list — a
          polite "9 runs" on first paint would be noise. */}
      <p className="sr-only" role="status" aria-live="polite">
        {narrowed ? `${shown} ${shown === 1 ? "run" : "runs"} shown` : ""}
      </p>

      {shown === 0 ? (
        <div className="history-empty">
          <p className="history-empty-title">No runs match.</p>
          <p className="history-empty-body">
            {query.trim()
              ? "Nothing in your last 20 runs has that in its title or summary. Try a shorter word, or show every source."
              : "None of your last 20 runs came from there."}
          </p>
          <button type="button" className="btn btn-secondary" onClick={clear}>
            Show all runs
          </button>
        </div>
      ) : (
        <div className="history-groups">
          {groups.map((group) => (
            <section key={group.bucket} className="history-group">
              <h2 className="history-group-label">{group.label}</h2>
              <ul className="poster-grid">
                {group.runs.map((run) => (
                  <Poster key={run.run_id} run={run} now={now} onOpen={onOpenRun} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </>
  );
}

function Poster({
  run,
  now,
  onOpen,
}: {
  run: RunSummary;
  now: Date;
  onOpen: HistoryPanelProps["onOpenRun"];
}) {
  const chip = platformLabel(run);
  const badge = posterBadge(run);
  const date = posterDate(run.created_at, now);
  const Glyph = isAudio(run) ? AudioLines : Play;

  return (
    <li className="poster-item" data-orientation={isLandscape(run) ? "landscape" : "portrait"}>
      <button
        type="button"
        className="poster"
        data-run-status={run.status}
        aria-label={posterLabel(run, now)}
        onClick={() => onOpen(run.run_id, run.source_kind)}
      >
        <span className="poster-thumb" data-tint={posterTint(run.run_id)} aria-hidden="true">
          {chip && <span className="poster-chip">{chip}</span>}
          <span className="poster-play">
            <Glyph className="poster-glyph" data-glyph={isAudio(run) ? "audio" : "play"} />
          </span>
          {badge && (
            <span className="poster-badge" data-kind={badge.kind}>
              {badge.text}
            </span>
          )}
        </span>
        <span className="poster-title" data-fallback={run.title?.trim() ? undefined : ""}>
          {posterTitle(run)}
        </span>
        {date && <span className="poster-date">{date}</span>}
      </button>
    </li>
  );
}
