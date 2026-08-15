"use client";

import { Fragment } from "react";
import { ArrowRight } from "lucide-react";
import { useRunHistory } from "@/application/useRunHistory";
import type { RunSummary } from "@/domain/entities";

/* Everything on a row is derived from what RunSummary actually carries —
   run_id, status, title, created_at. There is deliberately no platform,
   duration or thumbnail here: the API does not return them. */

const DAY_MS = 86_400_000;

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/* Day bucket derived from created_at. Today/Yesterday read better than a date
   for the two buckets people actually scan; everything older gets its real
   day so the grouping stays honestly per-day. */
function dayLabel(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "Undated";
  const days = Math.round((startOfDay(new Date()) - startOfDay(then)) / DAY_MS);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return then.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

/* The day header already carries the date, so the row's own stamp is the
   time within that day rather than a repeat of it. */
function timeLabel(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  return then.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function groupByDay(runs: RunSummary[]): { label: string; runs: RunSummary[] }[] {
  const groups: { label: string; runs: RunSummary[] }[] = [];
  for (const run of runs) {
    const label = dayLabel(run.created_at);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.runs.push(run);
    else groups.push({ label, runs: [run] });
  }
  return groups;
}

export default function HistoryPanel({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const { runs, error, retrying, retry } = useRunHistory();

  /* The pane drops its side padding for this view so row hover spans the full
     panel — the flat states have to carry that inset themselves. */
  if (error)
    /* .error-inline, not .error-block: this is one condition inside a panel,
       not the whole view having failed. The wording is the hook's — a server
       that answered gets its own `detail`, a server that never answered gets
       told so — and is never overwritten here. */
    return (
      <div role="alert" data-error-kind={error.kind} className="error-inline">
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
      <p role="status" className="pending-note">
        Loading…
      </p>
    );
  if (runs.length === 0)
    return <p className="pending-note">No previous runs yet.</p>;

  return (
    <ul className="history-list">
      {groupByDay(runs).map((group, index) => (
        /* keyed by position as well as label: an unparseable created_at drops a
           run into "Undated", which can legitimately appear more than once */
        <Fragment key={`${index}-${group.label}`}>
          <li>
            <p className="history-group">{group.label}</p>
          </li>
          {group.runs.map((run) => {
            const fallback = run.status === "failed" ? "Failed run" : "Untitled run";
            return (
              <li key={run.run_id}>
                <button
                  type="button"
                  onClick={() => onOpenRun(run.run_id)}
                  className="history-row min-h-12"
                  data-run-status={run.status}
                >
                  <span className="h-left">
                    <span className="h-dot" aria-hidden="true" />
                    <span className="h-text">
                      <span className="h-title" data-fallback={run.title ? undefined : ""}>
                        {run.title || fallback}
                      </span>
                      <span className="h-sub">
                        {run.status} &middot; {run.run_id.slice(0, 6)}
                      </span>
                    </span>
                  </span>
                  <span className="h-right">
                    <span className="h-meta">{timeLabel(run.created_at)}</span>
                    <ArrowRight className="h-go" aria-hidden="true" />
                  </span>
                </button>
              </li>
            );
          })}
        </Fragment>
      ))}
    </ul>
  );
}
