"use client";

import { useRunHistory } from "@/application/useRunHistory";
import { formatDate } from "@/components/format";

export default function HistoryPanel({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const { runs, error } = useRunHistory();

  if (error) return <p role="alert" className="text-sm text-[var(--color-danger)]">{error}</p>;
  if (runs === null) return <p className="text-sm text-[var(--color-faint)]">Loading…</p>;
  if (runs.length === 0) return <p className="text-sm text-[var(--color-faint)]">No previous runs yet.</p>;

  return (
    <ul className="flex flex-col divide-y divide-[var(--color-rule)]">
      {runs.map((run) => (
        <li key={run.run_id}>
          <button
            type="button"
            onClick={() => onOpenRun(run.run_id)}
            className="min-h-12 w-full rounded-[var(--radius-sm)] px-3 py-2.5 text-left transition-colors hover:bg-[var(--color-paper-2)]"
          >
            <span className="block max-w-full truncate text-sm font-medium text-[var(--color-text)]">
              {run.title || (run.status === "failed" ? "Failed run" : "Untitled run")}
            </span>
            <span className="mt-0.5 block text-xs text-[var(--color-faint)]">
              {formatDate(run.created_at)} &middot; {run.status}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
