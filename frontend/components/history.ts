/* History poster grid — the pure part. No React, no fetch, no storage: every
 * function here takes a RunSummary (or a list of them) plus, where time
 * matters, an explicit `now`, so each one is deterministic and the panel is
 * left with nothing but rendering.
 *
 * Every Phase 3 field on RunSummary is optional and nullable (runs stored
 * before the fields existed come back without them). Each helper's fallback is
 * "say nothing": no platform → no chip, no duration → no chip, no orientation
 * → portrait. Nothing here invents a value the server did not send.
 */

import type { RunSummary } from "@/domain/entities";

export type HistoryFilter = "all" | "instagram" | "tiktok" | "youtube" | "files";
export type HistorySort = "newest" | "oldest";

export const HISTORY_FILTERS: { id: HistoryFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "instagram", label: "Instagram" },
  { id: "tiktok", label: "TikTok" },
  { id: "youtube", label: "YouTube" },
  { id: "files", label: "Files" },
];

/* ---------- poster tint ---------- */

export type PosterTint = 1 | 2 | 3 | 4 | 5;

/** One of the five `--poster-N` tints, picked by a stable hash of run_id so a
 *  run keeps its colour across reloads, filters and sorts (FNV-1a, 32-bit). */
export function posterTint(runId: string): PosterTint {
  let hash = 0x811c9dc5;
  for (let i = 0; i < runId.length; i++) {
    hash ^= runId.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (((hash >>> 0) % 5) + 1) as PosterTint;
}

/* ---------- chips ---------- */

const PLATFORM_LABELS: Record<string, string> = {
  instagram: "Instagram",
  tiktok: "TikTok",
  youtube: "YouTube",
  audio_file: "Audio file",
  video_file: "Video file",
};

/** The top-left chip, or null for no chip. A known platform names itself; an
 *  `other` link or an unclassified run falls back to how it arrived ("Link" /
 *  "File") when that much is known, and to nothing when it is not. */
export function platformLabel(run: RunSummary): string | null {
  if (run.platform && PLATFORM_LABELS[run.platform]) return PLATFORM_LABELS[run.platform];
  if (run.source_kind === "link") return "Link";
  if (run.source_kind === "file") return "File";
  return null;
}

/** The centre glyph is a waveform rather than a play triangle for audio. */
export function isAudio(run: RunSummary): boolean {
  return run.platform === "audio_file";
}

/** Landscape posters span two columns at 16:9; everything else is a 3:4
 *  portrait, which is also the reading for a run with no orientation. */
export function isLandscape(run: RunSummary): boolean {
  return run.orientation === "landscape";
}

/** m:ss, or h:mm:ss past an hour. Null when there is nothing honest to show. */
export function formatDuration(seconds: number | null | undefined): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return null;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export type PosterBadge =
  | { kind: "duration"; text: string }
  | { kind: "failed"; text: string }
  | { kind: "processing"; text: string };

/** The bottom-right slot. Run state outranks duration: a failed or unfinished
 *  run says so there instead. */
export function posterBadge(run: RunSummary): PosterBadge | null {
  if (run.status === "failed") return { kind: "failed", text: "Failed" };
  if (run.status === "queued" || run.status === "processing") return { kind: "processing", text: "Processing" };
  const duration = formatDuration(run.duration_seconds);
  return duration ? { kind: "duration", text: duration } : null;
}

export const UNTITLED = "Untitled run";

export function posterTitle(run: RunSummary): string {
  return run.title?.trim() || UNTITLED;
}

/* ---------- dates ---------- */

const DAY_MS = 86_400_000;

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** Whole calendar days between `then` and `now` (0 = today), or null when the
 *  timestamp will not parse. Rounded because a DST change makes a "day" 23 or
 *  25 hours long. */
function daysAgo(iso: string, now: Date): number | null {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return null;
  return Math.round((startOfDay(now) - startOfDay(then)) / DAY_MS);
}

export type DayBucket = "today" | "week" | "earlier" | "undated";

export const BUCKET_LABELS: Record<DayBucket, string> = {
  today: "Today",
  week: "Earlier this week",
  earlier: "Earlier",
  undated: "Undated",
};

/** "This week" means the previous six days — exactly the window in which a
 *  bare weekday name ("Thu") is unambiguous, which is what the date line uses
 *  inside it. A future timestamp (clock skew) counts as today. */
export function dayBucket(iso: string, now: Date): DayBucket {
  const days = daysAgo(iso, now);
  if (days === null) return "undated";
  if (days <= 0) return "today";
  if (days <= 6) return "week";
  return "earlier";
}

/** "Today, 9:41 PM" · "Yesterday, 8:15 PM" · "Thu, 7:02 PM" · "Oct 12, 7:02 PM"
 *  (plus the year when it is not this one). Empty when unparseable. */
export function posterDate(iso: string, now: Date): string {
  const then = new Date(iso);
  const days = daysAgo(iso, now);
  if (days === null) return "";
  const time = then.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  let day: string;
  if (days <= 0) day = "Today";
  else if (days === 1) day = "Yesterday";
  else if (days <= 6) day = then.toLocaleDateString(undefined, { weekday: "short" });
  else
    day = then.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      ...(then.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}),
    });
  return `${day}, ${time}`;
}

/* ---------- filter / search / sort ---------- */

export function matchesFilter(run: RunSummary, filter: HistoryFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "files":
      return run.source_kind === "file" || run.platform === "audio_file" || run.platform === "video_file";
    default:
      return run.platform === filter;
  }
}

/** Every whitespace-separated term must appear somewhere in the title or the
 *  summary snippet, case-insensitively. An empty query matches everything. */
export function matchesQuery(run: RunSummary, query: string): boolean {
  const terms = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = `${run.title ?? ""}\n${run.summary_snippet ?? ""}`.toLocaleLowerCase();
  return terms.every((term) => haystack.includes(term));
}

function timeOf(iso: string): number | null {
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : t;
}

/** A copy, sorted by created_at. Unparseable timestamps go last in either
 *  order, so "Undated" is always one group at the end. */
export function sortRuns(runs: RunSummary[], order: HistorySort): RunSummary[] {
  const sign = order === "newest" ? -1 : 1;
  return [...runs].sort((a, b) => {
    const ta = timeOf(a.created_at);
    const tb = timeOf(b.created_at);
    if (ta === null || tb === null) return ta === tb ? 0 : ta === null ? 1 : -1;
    return sign * (ta - tb);
  });
}

export interface HistoryGroup {
  bucket: DayBucket;
  label: string;
  runs: RunSummary[];
}

/** Filter, search, sort, then bucket. Runs arrive sorted, so each bucket is
 *  one contiguous stretch and becomes exactly one group. */
export function buildHistory(
  runs: RunSummary[],
  { filter, query, sort, now }: { filter: HistoryFilter; query: string; sort: HistorySort; now: Date }
): HistoryGroup[] {
  const visible = sortRuns(
    runs.filter((run) => matchesFilter(run, filter) && matchesQuery(run, query)),
    sort
  );
  const groups: HistoryGroup[] = [];
  for (const run of visible) {
    const bucket = dayBucket(run.created_at, now);
    const last = groups[groups.length - 1];
    if (last && last.bucket === bucket) last.runs.push(run);
    else groups.push({ bucket, label: BUCKET_LABELS[bucket], runs: [run] });
  }
  return groups;
}

/** The poster's accessible name: title first (so it contains the visible
 *  label, WCAG 2.5.3), then whatever the poster shows around it. */
export function posterLabel(run: RunSummary, now: Date): string {
  const parts = [posterTitle(run)];
  const platform = platformLabel(run);
  if (platform) parts.push(platform);
  const badge = posterBadge(run);
  if (badge) parts.push(badge.kind === "duration" ? `duration ${badge.text}` : badge.text);
  const date = posterDate(run.created_at, now);
  if (date) parts.push(date);
  return parts.join(", ");
}
