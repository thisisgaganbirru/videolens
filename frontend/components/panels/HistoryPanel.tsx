"use client";

import { useId, useMemo, useState } from "react";
import { AudioLines, ChevronDown, Play, Trash2 } from "lucide-react";
import { HISTORY_LIMIT, useRunHistory, type HistoryEntry } from "@/application/useRunHistory";
import {
  deleteAllSavedRuns,
  deleteSavedRun,
  goneSavedRuns,
  loadMoreSaved,
  refreshSavedHistory,
  SAVED_PAGE_SIZE,
  type SavedHistoryState,
} from "@/application/useSavedHistory";
import type { SavedOpenOutcome } from "@/application/useAnalysisRun";
import { classifyGatewayError } from "@/application/gatewayError";
import type { RunSourceKind, SavedRunSummary } from "@/domain/entities";
import ConfirmDialog from "@/components/ConfirmDialog";
import { formatLongDay } from "@/components/format";
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

/* History — a poster grid (design/shots/HistoryA*.png, HistoryMobile.png,
   HistoryWeb.png). Everything that decides *what* shows lives in the pure
   components/history.ts; this file only renders. Filtering, search and sort
   are client-side over the <=20 runs this browser keeps (IndexedDB, Phase
   5a) — there is no paging to coordinate with.

   Paid saved history (2026-11-14, docs/frontend/saved-history.md): while the
   signed-in account saves runs (or its plan ended and they are kept until a
   date), the page lists the account's runs, newest first, a page at a time
   with "Load more", and puts what only this browser has in a second, quieter
   group. Search, filters and sort are left out there: over a partly loaded
   list they would answer for some runs and silently not for the rest. Every
   other case (anonymous, free, an older backend, sign-in off) is exactly the
   browser-only page above. */

interface HistoryPanelProps {
  onOpenRun: (runId: string, sourceKind?: RunSourceKind | null) => void;
  /** Leaves History for the intake — the empty state's one action. */
  onAnalyze: () => void;
  /** The signed-in account's saved runs (useSavedHistory). Absent or `off`:
   *  the browser-only page. */
  saved?: SavedHistoryState;
  /** The plan or the run count says paid; decides how a slow first read
   *  looks (loading posters, or today's page until it answers). */
  paid?: boolean;
  onOpenSaved?: (summary: SavedRunSummary) => Promise<SavedOpenOutcome>;
  onOpenAccount?: () => void;
}

/** "December 14, 2026", or null for nothing honest to show. */
function longDay(iso: string | null | undefined): string | null {
  if (!iso) return null;
  return Number.isNaN(new Date(iso).getTime()) ? null : formatLongDay(iso);
}

export default function HistoryPanel(props: HistoryPanelProps) {
  const { onOpenRun, onAnalyze, saved, paid = false } = props;
  const local = useRunHistory();
  const mode = saved?.mode ?? "off";
  const savedView =
    saved && (mode === "saving" || mode === "window" || mode === "failed" || (mode === "pending" && paid));

  if (savedView && saved) return <SavedHistory {...props} saved={saved} local={local} />;

  return (
    <div className="history">
      <header className="history-head">
        <h1 className="history-title">History</h1>
        <p className="history-lede">Your last {HISTORY_LIMIT} runs, saved in this browser. Not synced.</p>
      </header>
      <HistoryBody {...local} onOpenRun={onOpenRun} onAnalyze={onAnalyze} />
      {/* After the list, not above it: the hold is learned from a read that
          lands after first paint, and a notice above would push the page. */}
      {mode === "held" ? (
        <div className="history-notice" role="status">
          <p>
            Your account is scheduled for deletion, so runs saved to it are not shown here. Restore it
            from Account to bring them back.
          </p>
          {props.onOpenAccount ? (
            <button type="button" className="acct-link" onClick={props.onOpenAccount}>
              Go to Account
            </button>
          ) : null}
        </div>
      ) : null}
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
}: ReturnType<typeof useRunHistory> & Pick<HistoryPanelProps, "onOpenRun" | "onAnalyze">) {
  /* The browser will not store anything (some private modes). Nothing is
     broken and nothing can be retried, so this is the calm empty-state
     voice, not the red failure ladder — and the way forward is the app,
     which still works. */
  if (error?.kind === "storage")
    return (
      <div className="history-empty" data-error-kind="storage" role="status">
        <p className="history-empty-title">{error.message}</p>
        <p className="history-empty-body">
          This browser isn&apos;t letting VideoLens save anything, which private browsing often
          does. You can still analyze videos; their results just won&apos;t be kept here
          afterwards.
        </p>
        <button type="button" className="btn btn-primary" onClick={onAnalyze}>
          Analyze a video
        </button>
      </div>
    );
  /* .error-inline, not .error-block: one condition inside a view, not the
     whole app having failed. The wording is the hook's. */
  if (error)
    return (
      <div role="alert" className="error-inline history-state" data-error-kind={error.kind}>
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
  /* Nothing has been analyzed in this browser yet (or History was cleared).
     Not an error, so no red and no retry: one way forward instead. */
  if (runs.length === 0)
    return (
      <div className="history-empty">
        <p className="history-empty-title">No runs yet.</p>
        <p className="history-empty-body">
          Analyze a link or a file and it will wait here, so you can read its notes again later.
        </p>
        <button type="button" className="btn btn-primary" onClick={onAnalyze}>
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
  runs: HistoryEntry[];
  onOpenRun: HistoryPanelProps["onOpenRun"];
}) {
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<HistorySort>("newest");
  const searchId = useId();
  const sortId = useId();

  /* Sort is on every width since refinement 4 (HIS-03): the phone boards drew
     none, so portrait had no way to see the oldest runs first while landscape
     did. On a phone it shares the search row (globals.css, HISTORY block). */

  /* "Today" is fixed for the life of this list rather than read on every
     keystroke, so a run cannot hop groups mid-search at midnight. A fresh
     visit to the tab remounts and reads it again. */
  const now = useMemo(() => new Date(), []);
  const groups = useMemo(
    () => buildHistory(runs, { filter, query, sort, now }),
    [runs, filter, query, sort, now]
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
            placeholder="Search runs"
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
                  <Poster key={run.run_id} run={run} now={now} onOpen={() => onOpenRun(run.run_id, run.source_kind)} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </>
  );
}

/* ---------- saved to the account ---------- */

/** A saved run as the poster grid draws it. Saved runs are finished runs. */
function savedEntry(item: SavedRunSummary): HistoryEntry {
  const source = item.source ?? null;
  return {
    run_id: item.run_id,
    status: "complete",
    title: item.title?.trim() || source?.source_title?.trim() || null,
    created_at: item.created_at,
    source_kind: source?.source_kind ?? null,
    platform: source?.platform ?? null,
    duration_seconds: source?.duration_seconds ?? null,
    summary_snippet: item.summary_snippet ?? null,
    width: source?.width ?? null,
    height: source?.height ?? null,
    thumbnail_url: item.thumbnail ?? null,
    expired: false,
  };
}

type PendingDelete = { kind: "one"; summary: SavedRunSummary } | { kind: "all" };

const DELETE_ONE_FALLBACK = "That run could not be deleted. Nothing changed.";
const DELETE_ALL_FALLBACK = "Your saved runs could not be deleted. Nothing changed.";

function SavedHistory({
  onOpenRun,
  onAnalyze,
  onOpenSaved,
  onOpenAccount,
  saved,
  local,
}: HistoryPanelProps & { saved: SavedHistoryState; local: ReturnType<typeof useRunHistory> }) {
  const now = useMemo(() => new Date(), []);
  const [opening, setOpening] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingDelete | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const keptUntil = longDay(saved.status?.expires_at);
  const loading = saved.mode === "pending" || (!saved.settled && saved.items.length === 0);
  const failed = saved.mode === "failed";

  /* Runs found gone (404) since the list was read, fixed at mount so the
     list never drops a card while it is still on screen. */
  const [hidden] = useState(goneSavedRuns);
  const items = useMemo(
    () => (hidden.size > 0 ? saved.items.filter((item) => !hidden.has(item.run_id)) : saved.items),
    [saved.items, hidden]
  );
  const savedGroups = useMemo(
    () => buildHistory(items.map(savedEntry), { filter: "all", query: "", sort: "newest", now }),
    [items, now]
  );
  const byId = useMemo(() => new Map(items.map((item) => [item.run_id, item])), [items]);

  /* What only this browser has: not among the account's loaded runs, and
     (while more pages are still on the server) no older than the oldest one
     loaded, so a run that is on a later page is not shown as browser-only.
     After a failed read the server's list is unknown: everything local. */
  const localOnly = useMemo(() => {
    if (!local.runs) return [];
    if (failed) return local.runs;
    const oldest = items.length > 0 ? items[items.length - 1].created_at : null;
    const floor = saved.nextCursor && oldest ? new Date(oldest).getTime() : null;
    return local.runs.filter((run) => {
      if (byId.has(run.run_id)) return false;
      if (floor === null) return true;
      const t = new Date(run.created_at).getTime();
      return Number.isNaN(t) || t >= floor;
    });
  }, [local.runs, failed, items, saved.nextCursor, byId]);
  const localGroups = useMemo(
    () => buildHistory(localOnly, { filter: "all", query: "", sort: "newest", now }),
    [localOnly, now]
  );

  const open = async (summary: SavedRunSummary) => {
    if (!onOpenSaved || opening) return;
    setOpenError(null);
    setOpening(summary.run_id);
    const outcome = await onOpenSaved(summary);
    /* Shown or gone: History is being left, so nothing here is redrawn
       (a redraw would drop a gone card under the finger, a visible shift). */
    if (outcome.kind === "shown" || outcome.kind === "gone") return;
    setOpening(null);
    if (outcome.kind === "error") setOpenError(outcome.message);
  };

  const confirmDelete = async () => {
    if (!pending || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      if (pending.kind === "one") await deleteSavedRun(pending.summary.run_id);
      else await deleteAllSavedRuns();
      setPending(null);
    } catch (err: unknown) {
      setDeleteError(
        classifyGatewayError(err, pending.kind === "one" ? DELETE_ONE_FALLBACK : DELETE_ALL_FALLBACK).message
      );
    } finally {
      setDeleting(false);
    }
  };

  const ask = (next: PendingDelete) => {
    setDeleteError(null);
    setPending(next);
  };

  const emptySaved = saved.settled && !failed && items.length === 0;

  return (
    <div className="history" data-saved={saved.mode}>
      <header className="history-head">
        <h1 className="history-title">History</h1>
        <p className="history-lede">
          {saved.mode === "window"
            ? "Runs saved to your account, on any device where you sign in."
            : "Every run is saved to your account, so it is here on any device where you sign in."}
        </p>
      </header>

      {saved.mode === "window" ? (
        <div className="history-notice" role="status">
          <p>
            Your plan has ended, so new runs are no longer saved.{" "}
            {keptUntil
              ? `These are kept until ${keptUntil}, then deleted. Resubscribe before then and they stay.`
              : "These are kept for 30 days after the plan ended, then deleted. Resubscribe before then and they stay."}
          </p>
          {onOpenAccount ? (
            <button type="button" className="acct-link" onClick={onOpenAccount}>
              Go to Account
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="history-saved-alert" aria-live="polite">
        {openError ? (
          <p role="alert" className="error-inline history-state">
            {openError}
          </p>
        ) : null}
      </div>

      {loading ? (
        <SavedLoading />
      ) : failed ? (
        <div role="alert" className="error-inline history-state">
          <p>Your saved runs could not be loaded. Check your connection and try again.</p>
          <button
            type="button"
            className="btn btn-secondary"
            aria-disabled={saved.refreshing || undefined}
            onClick={() => {
              if (!saved.refreshing) void refreshSavedHistory();
            }}
          >
            {saved.refreshing ? "Retrying…" : "Try again"}
          </button>
        </div>
      ) : emptySaved ? (
        <div className="history-empty">
          <p className="history-empty-title">No saved runs yet.</p>
          <p className="history-empty-body">
            {saved.mode === "window"
              ? "Nothing was saved to your account while the plan was active."
              : "Every run you finish is saved here, and shows up in History on any device where you sign in."}
          </p>
          {saved.mode === "saving" ? (
            <button type="button" className="btn btn-primary" onClick={onAnalyze}>
              Analyze a video
            </button>
          ) : null}
        </div>
      ) : (
        <>
          <div className="history-groups">
            {savedGroups.map((group, index) => (
              <section key={group.bucket} className="history-group">
                <h2 className="history-group-label">{group.label}</h2>
                <ul className="poster-grid">
                  {group.runs.map((run) => {
                    const summary = byId.get(run.run_id);
                    return (
                      <Poster
                        key={run.run_id}
                        run={run}
                        now={now}
                        busy={opening === run.run_id}
                        onOpen={() => {
                          if (summary) void open(summary);
                        }}
                        onDelete={summary ? () => ask({ kind: "one", summary }) : undefined}
                      />
                    );
                  })}
                  {/* Load more (2026-11-14): the next page's space is taken
                      the moment it is asked for, at the end of the last
                      group (where an older page usually continues), so the
                      control moves with the press and the posters land in
                      place instead of pushing it down when they arrive. */}
                  {saved.loadingMore && index === savedGroups.length - 1 ? <GhostPosters count={SAVED_PAGE_SIZE} /> : null}
                </ul>
              </section>
            ))}
          </div>
          <div className="history-saved-foot">
            {saved.nextCursor ? (
              <button
                type="button"
                className="btn btn-secondary"
                aria-disabled={saved.loadingMore || undefined}
                onClick={() => {
                  if (!saved.loadingMore) void loadMoreSaved();
                }}
              >
                {saved.loadingMore ? "Loading…" : saved.loadMoreFailed ? "Try again" : "Load more runs"}
              </button>
            ) : null}
            <button type="button" className="acct-link history-delete-all" onClick={() => ask({ kind: "all" })}>
              Delete all saved runs
            </button>
          </div>
          <p className="sr-only" role="status" aria-live="polite">
            {saved.loadMoreFailed ? "More runs could not be loaded." : ""}
          </p>
          {saved.loadMoreFailed ? (
            <p className="history-saved-note">More runs could not be loaded. Check your connection and try again.</p>
          ) : null}
        </>
      )}

      {localGroups.length > 0 ? (
        <section className="history-local" aria-labelledby="history-local-title">
          <h2 id="history-local-title" className="history-group-label">
            Only in this browser
          </h2>
          <p className="history-local-note">
            {failed
              ? "What this browser keeps on its own. Not synced."
              : "Not saved to your account: runs from before your plan, and runs that did not finish. Not synced."}
          </p>
          {localGroups.map((group) => (
            <section key={group.bucket} className="history-group" aria-label={group.label}>
              <ul className="poster-grid">
                {group.runs.map((run) => (
                  <Poster
                    key={run.run_id}
                    run={run}
                    now={now}
                    onOpen={() => onOpenRun(run.run_id, run.source_kind)}
                  />
                ))}
              </ul>
            </section>
          ))}
        </section>
      ) : null}

      <ConfirmDialog
        open={pending !== null}
        title={pending?.kind === "all" ? "Delete all saved runs?" : "Delete this run?"}
        confirmLabel={pending?.kind === "all" ? "Delete all saved runs" : "Delete run"}
        busyLabel="Deleting…"
        busy={deleting}
        error={deleteError}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPending(null)}
      >
        {pending?.kind === "all" ? (
          <p>
            Every run saved to your account is removed, on every device. This cannot be undone. Runs this
            browser keeps on its own stay here.
          </p>
        ) : pending ? (
          <p>
            &ldquo;{posterTitle(savedEntry(pending.summary))}&rdquo; is removed from your account, on every
            device. This cannot be undone. A copy this browser keeps on its own stays here.
          </p>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

/* While the first page is on its way: one row of blank posters the size of
   the real ones, so the grid lands in space already taken. */
function GhostPosters({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, n) => (
        <li key={`ghost-${n}`} className="poster-item history-ghost" aria-hidden="true">
          <span className="poster">
            <span className="poster-thumb history-ghost-thumb" />
            <span className="poster-title history-ghost-line" />
            <span className="poster-date history-ghost-line history-ghost-line--short" />
          </span>
        </li>
      ))}
    </>
  );
}

function SavedLoading() {
  return (
    <div className="history-groups">
      <p role="status" className="sr-only">
        Loading your saved runs…
      </p>
      <section className="history-group history-ghost" aria-hidden="true">
        <span className="history-group-label history-ghost-label" />
        <ul className="poster-grid">
          {[0, 1, 2, 3, 4].map((n) => (
            <li key={n} className="poster-item">
              <span className="poster">
                <span className="poster-thumb history-ghost-thumb" />
                <span className="poster-title history-ghost-line" />
                <span className="poster-date history-ghost-line history-ghost-line--short" />
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Poster({
  run,
  now,
  onOpen,
  onDelete,
  busy = false,
}: {
  run: HistoryEntry;
  now: Date;
  onOpen: () => void;
  /** Saved runs only: removes it from the account (after a confirmation). */
  onDelete?: () => void;
  busy?: boolean;
}) {
  const chip = platformLabel(run);
  const badge = posterBadge(run);
  const date = posterDate(run.created_at, now);
  const Glyph = isAudio(run) ? AudioLines : Play;

  return (
    <li
      className="poster-item"
      data-orientation={isLandscape(run) ? "landscape" : "portrait"}
      data-deletable={onDelete ? "" : undefined}
    >
      <button
        type="button"
        className="poster"
        data-run-status={run.expired ? "expired" : run.status}
        aria-label={posterLabel(run, now)}
        aria-busy={busy || undefined}
        onClick={onOpen}
      >
        <span className="poster-thumb" data-tint={posterTint(run.run_id)} aria-hidden="true">
          {/* The stored poster, over the tint (which stays as the colour
              behind it while it decodes). Empty alt: the button's label
              already names the run. A plain <img>: the source is a blob:
              URL from IndexedDB (or the account's data: URL), which
              next/image cannot optimise. */}
          {run.thumbnail_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="poster-img" src={run.thumbnail_url} alt="" decoding="async" draggable={false} />
          )}
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
        {date && <span className="poster-date">{busy ? "Opening…" : date}</span>}
      </button>
      {onDelete ? (
        <button
          type="button"
          className="poster-delete"
          aria-label={`Delete ${posterTitle(run)} from your account`}
          onClick={onDelete}
        >
          <span className="poster-delete__disc" aria-hidden="true">
            <Trash2 className="poster-delete__icon" />
          </span>
        </button>
      ) : null}
    </li>
  );
}
