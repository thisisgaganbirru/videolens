"use client";

import { useVersionLog } from "@/application/useVersionLog";
import { formatDate } from "@/components/format";

export default function VersionLogPanel() {
  const { entries, error } = useVersionLog();

  if (error) return <p role="alert" className="text-sm text-[var(--color-danger)]">{error}</p>;
  if (entries === null) return <p className="text-sm text-[var(--color-faint)]">Loading…</p>;
  if (entries.length === 0) return <p className="text-sm text-[var(--color-faint)]">No releases yet.</p>;

  return (
    <ul className="flex flex-col divide-y divide-[var(--color-rule)]">
      {entries.map((entry) => (
        <li key={entry.tag} className="py-2.5">
          <a
            href={entry.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex flex-col justify-center gap-0.5 rounded-[var(--radius-sm)] px-2 py-1 transition-colors hover:bg-[var(--color-paper-2)]"
          >
            <span className="text-sm font-medium text-[var(--color-text)]">{entry.name}</span>
            <span className="text-xs text-[var(--color-faint)]">{formatDate(entry.publishedAt)}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}
