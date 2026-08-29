"use client";

import { ExternalLink } from "lucide-react";
import { useVersionLog } from "@/application/useVersionLog";
import { formatDate } from "@/components/format";

/* No drawn spec for this view in the terminal mockup — it is built by analogy
   to the history list: hairline-separated rows, square corners, no fill and no
   shadow, with the accent spent only on the hover/focus affordance. Unlike
   history, the releases pane keeps its side padding, so a row reads as a line
   of text rather than a full-bleed band, and hover recolours the title instead
   of painting an inset block. Every value is a token; nothing is hardcoded. */

export default function VersionLogPanel() {
  const { entries, error, retrying, retry } = useVersionLog();

  /* .error-inline, the third rung of the ladder documented in globals.css above
     .pending-note — and it is that rung *because* it now carries a retry.
     `.error-note`, the rung below, is defined as a rejection sitting beside the
     control that caused it; nothing here was user-triggered, so that definition
     does not describe this either. The rung that can be made to fit honestly is
     this one, and it fits by supplying the thing that was actually missing:
     the release fetch fails when the device is offline, and offline ends. Until
     now the only recovery was a full reload or the accident of switching tabs
     and back. This is also the same object HistoryPanel renders one tab over —
     a fetch-on-mount gateway list with the same four states — so it gets the
     same treatment and the same `.btn .btn-secondary` control.
     `role="alert"` not `role="status"`: the earlier reasoning for `status` was
     "there is nothing to act on", which the retry retires. */
  if (error)
    return (
      <div role="alert" className="error-inline">
        <p>{error}</p>
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
  if (entries === null) return <p className="pending-note">Loading…</p>;
  if (entries.length === 0) return <p className="pending-note">No releases yet.</p>;

  return (
    <ul className="m-0 list-none p-0">
      {entries.map((entry) => (
        <li
          key={entry.tag}
          className="border-b border-[var(--color-rule)] last:border-b-0"
        >
          <a
            href={entry.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group flex min-h-12 items-center justify-between gap-[var(--space-sm)] py-[var(--space-xs)] no-underline outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)]"
          >
            <span className="h-text">
              <span className="text-[0.8rem] leading-[1.35] text-[var(--color-ink)] transition-colors duration-[var(--dur-short)] group-hover:text-[var(--color-accent)]">
                {entry.name}
              </span>
              {/* tag and date are both genuinely in VersionLogEntry */}
              <span className="h-sub">
                {entry.tag} &middot; {formatDate(entry.publishedAt)}
              </span>
            </span>
            <ExternalLink
              className="h-3.5 w-3.5 shrink-0 text-[var(--color-muted)] transition-colors duration-[var(--dur-short)] group-hover:text-[var(--color-accent)]"
              aria-hidden="true"
            />
          </a>
        </li>
      ))}
    </ul>
  );
}
