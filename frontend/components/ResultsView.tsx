"use client";

import { useCallback, useId, useRef, useState, type KeyboardEvent } from "react";
import { useResultExport } from "@/application/useResultExport";
import type { MarkdownDocument } from "@/domain/ports";
import { ArrowUpRight, Check, ChevronDown, ChevronLeft, ChevronRight, Copy, Share2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { safeHttpUrl } from "./safeUrl";
import { splitTakeaway } from "./takeaway";
import { formatDuration } from "./history";
import { platformKey, platformName } from "@/domain/platforms";
import type {
  AnalysisCompleteness,
  ScreenTextSegment,
  SourceMetadata,
  TranscriptSegment,
  VideoAnalysis,
} from "@/domain/entities";

/* ---- caption-only runs ----
   When every download route for a URL fails, the backend salvages the run by
   analyzing the subtitle track instead. The result then looks like any other
   successful analysis with an empty on-screen-text section — and a reader who
   sees a transcript and no screen text concludes the video had none. It had no
   frames at all. Two corrections, and only two:

     1. one line under the title band, where the impression of the result
        forms;
     2. the on-screen-text empty state, which is the exact place the false
        inference happens.

   The transcript tab deliberately gets nothing of its own. The line above is
   in the pane header, outside the scroller, so it is still on screen while the
   transcript is read; a second copy there would be the same sentence twice.

   Both strings are shared with the downloadable report, because the report is
   the copy that outlives the session. */
const CAPTIONS_ONLY_LEAD = "Caption track only.";
/* Second sentence names *the transcript* rather than warning about captions in
   the abstract: the transcript is the thing a reader quotes, and naming it here
   is what lets the transcript tab stay unannotated. */
const CAPTIONS_ONLY_BODY =
  "The video could not be downloaded, so this analysis read its captions and never saw a frame. Auto-generated captions mishear words, so the transcript is approximate.";
const CAPTIONS_ONLY_NO_SCREEN_TEXT =
  "No frames were analyzed — this run read the caption track only, so on-screen text was never looked for.";
const FULL_NO_SCREEN_TEXT = "No on-screen text was detected.";

// Order is the reading order we want people to take: the shortest read first,
// then the full notes, then the two raw sources behind them.
const TABS = [
  { key: "summary", label: "TL;DR" },
  { key: "markdown", label: "Notes" },
  { key: "transcript", label: "Transcript" },
  { key: "screen_text", label: "On-screen" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

/* Refinement 4 (RES-05): Copy takes only the tab on screen, Share and
   Download the whole report — and nothing said so. Copy's name, tooltip and
   confirmation now name the section; Share's name says "all". The wording
   for each tab, as the object of "Copy …" and the subject of "… copied". */
const COPY_NOUN: Record<TabKey, string> = {
  summary: "TL;DR",
  markdown: "notes",
  transcript: "transcript",
  screen_text: "on-screen text",
};

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/* TL;DR opens first: the shortest read, the thing to have in front of you the
   moment a run finishes. (Phase 2 briefly opened on Notes to match the boards;
   the owner reverted that on 2026-11-01 — TL;DR is the default.) */
const DEFAULT_TAB: TabKey = "summary";
type TimelineSegment = ScreenTextSegment | TranscriptSegment;

function formatTimestamp(value: number) {
  const totalSeconds = Math.max(0, Math.round(value));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds
      .toString()
      .padStart(2, "0")}`;
  }
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/**
 * The On-screen tab, text only (design/newshots/ResultsOnScreenText*.png): one
 * line of context, then a row per moment — the start time in the accent
 * column, the text found in the frame beside it in serif, one line per line
 * the model returned (a card listing "Grain / Protein / Veg" stays three
 * lines). Only the start time is shown; the end is carried in the `title` and
 * `dateTime`. The backend sends no frames, so there are no thumbnails.
 */
function OnScreenView({
  segments,
  fallback,
  emptyMessage,
}: {
  segments: ScreenTextSegment[];
  fallback: string;
  emptyMessage: string;
}) {
  const text = fallback.trim();
  if (segments.length === 0 && !text) {
    return <p className="t-intro">{emptyMessage}</p>;
  }

  return (
    <>
      <p className="t-intro">Text found in the video frames, with the time it appears.</p>
      {segments.length === 0 ? (
        /* An older run, or a model reply without timings: the text alone. */
        <p className="screen-text" dir="auto">
          {text}
        </p>
      ) : (
        <ol className="t-list t-list--screen" aria-label="On-screen text by time">
          {segments.map((segment, index) => (
            <li key={`${segment.start_seconds}-${segment.end_seconds}-${index}`} className="t-row">
              <time
                dateTime={`PT${Math.max(0, Math.round(segment.start_seconds))}S`}
                title={`${formatTimestamp(segment.start_seconds)}–${formatTimestamp(segment.end_seconds)}`}
                className="t-time"
              >
                {formatTimestamp(segment.start_seconds)}
              </time>
              <p className="t-text" dir="auto">
                {segment.text.trim()}
              </p>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** `text` with every case-insensitive occurrence of `query` wrapped in <mark>. */
function highlight(text: string, query: string) {
  if (!query) return text;
  const parts = text.split(new RegExp(`(${escapeRegExp(query)})`, "gi"));
  return parts.map((part, index) => (index % 2 === 1 ? <mark key={index}>{part}</mark> : part));
}

/**
 * The Transcript tab, drawn on design/shots/ResultsTranscript.png: a search
 * box that filters the rows and marks the matches, a switch that hides the
 * timestamp column, then the rows. Both controls are local view state — they
 * change what is shown, never what is copied, shared or downloaded.
 *
 * With no timed segments there is nothing to search or time, so the toolbar is
 * not drawn and the plain transcript (or the empty message) reads as prose.
 */
function TranscriptView({ segments, fallback }: { segments: TranscriptSegment[]; fallback: string }) {
  const [query, setQuery] = useState("");
  const [showTimes, setShowTimes] = useState(true);
  const searchId = useId();
  const searchRef = useRef<HTMLInputElement>(null);

  if (segments.length === 0) {
    return (
      <p className="prose-serif whitespace-pre-wrap break-words" dir="auto">
        {fallback || "No spoken content was detected."}
      </p>
    );
  }

  const needle = query.trim();
  const lowered = needle.toLowerCase();
  const visible = needle
    ? segments.filter(
        (segment) =>
          segment.text.toLowerCase().includes(lowered) ||
          (segment.speaker ?? "").toLowerCase().includes(lowered),
      )
    : segments;

  /* Polite and atomic, and only while a search is active: it says how many
     rows the filter left. Silent with no query, where the count is just "all
     of them". */
  const countMessage = needle
    ? `${visible.length} ${visible.length === 1 ? "line matches" : "lines match"} “${needle}”.`
    : "";

  return (
    <>
      <div className="t-toolbar">
        <div className="t-search">
          <label htmlFor={searchId} className="sr-only">
            Search transcript
          </label>
          <input
            ref={searchRef}
            id={searchId}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search transcript"
            autoComplete="off"
            className="field field-pill"
          />
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={showTimes}
          onClick={() => setShowTimes((value) => !value)}
          className="switch-row"
        >
          <span className="switch" aria-hidden="true" />
          Timestamps
        </button>
      </div>

      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {countMessage}
      </p>

      {visible.length === 0 ? (
        <div className="t-empty">
          <p className="pending-note">Nothing in this transcript matches “{needle}”.</p>
          <button
            type="button"
            className="reset-link"
            onClick={() => {
              setQuery("");
              searchRef.current?.focus();
            }}
          >
            Clear search
          </button>
        </div>
      ) : (
        <ol className="t-list" data-times={showTimes ? "on" : "off"} aria-label="Timestamped transcript">
          {visible.map((segment, index) => (
            <li key={`${segment.start_seconds}-${segment.end_seconds}-${index}`} className="t-row">
              {showTimes ? (
                <time
                  dateTime={`PT${Math.max(0, Math.round(segment.start_seconds))}S`}
                  title={`${formatTimestamp(segment.start_seconds)}–${formatTimestamp(segment.end_seconds)}`}
                  className="t-time"
                >
                  {formatTimestamp(segment.start_seconds)}
                </time>
              ) : null}
              <div className="t-body">
                {segment.speaker ? (
                  <span className="t-speaker" dir="auto">
                    {highlight(segment.speaker, needle)}
                  </span>
                ) : null}
                <p className="t-text" dir="auto">
                  {highlight(segment.text, needle)}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

function singleLine(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function timelineMarkdown(segments: TimelineSegment[], fallback: string, emptyMessage: string) {
  if (segments.length === 0) return fallback.trim() || `_${emptyMessage}_`;

  return segments
    .map((segment) => {
      const speaker = "speaker" in segment && segment.speaker ? ` — ${singleLine(segment.speaker)}` : "";
      return `### ${formatTimestamp(segment.start_seconds)}–${formatTimestamp(segment.end_seconds)}${speaker}\n\n${segment.text.trim()}`;
    })
    .join("\n\n");
}

function buildMarkdownReport(
  result: VideoAnalysis,
  sourceMetadata?: SourceMetadata | null,
  completeness: AnalysisCompleteness = "full",
) {
  const captionsOnly = completeness === "captions_only";
  const sections = [`# ${singleLine(result.title)}`];

  /* Directly under the title, for the same reason the on-screen note sits
     beside it: the file is read top-down and this qualifies everything below
     it. Leaving it out would export the exact false claim the UI now corrects,
     into the copy the user keeps. */
  if (captionsOnly) {
    sections.push(`> **${CAPTIONS_ONLY_LEAD}** ${CAPTIONS_ONLY_BODY}`);
  }

  if (sourceMetadata) {
    const sourceDetails = [
      `- **Platform:** ${singleLine(platformName(sourceMetadata.platform))}`,
      sourceMetadata.title && `- **Source title:** ${singleLine(sourceMetadata.title)}`,
      sourceMetadata.uploader &&
        `- **Creator:** ${
          safeHttpUrl(sourceMetadata.uploader_url)
            ? `[${singleLine(sourceMetadata.uploader)}](<${safeHttpUrl(sourceMetadata.uploader_url)}>)`
            : singleLine(sourceMetadata.uploader)
        }`,
      sourceMetadata.upload_date && `- **Published:** ${singleLine(sourceMetadata.upload_date)}`,
      sourceMetadata.view_count != null && `- **Views:** ${sourceMetadata.view_count.toLocaleString("en-US")}`,
      sourceMetadata.like_count != null && `- **Likes:** ${sourceMetadata.like_count.toLocaleString("en-US")}`,
      sourceMetadata.comment_count != null &&
        `- **Comments:** ${sourceMetadata.comment_count.toLocaleString("en-US")}`,
      safeHttpUrl(sourceMetadata.source_url) && `- **Original post:** <${safeHttpUrl(sourceMetadata.source_url)}>`,
    ].filter((line): line is string => Boolean(line));

    if (sourceMetadata.description) {
      sourceDetails.push(`\n### Source caption\n\n${sourceMetadata.description.trim()}`);
    }
    sections.push(`## Source\n\n${sourceDetails.join("\n")}`);
  }

  sections.push(
    `## Summary\n\n${result.summary.trim() || "_No summary was generated._"}`,
    `## Notes\n\n${result.markdown.trim() || "_No notes were generated._"}`,
    `## Transcript\n\n${timelineMarkdown(
      result.transcript_segments ?? [],
      result.transcript,
      "No transcript was detected.",
    )}`,
    `## On-screen Text\n\n${timelineMarkdown(
      result.screen_text_segments ?? [],
      result.screen_text,
      captionsOnly ? CAPTIONS_ONLY_NO_SCREEN_TEXT : FULL_NO_SCREEN_TEXT,
    )}`,
  );

  return `${sections.join("\n\n")}\n`;
}

/* The whole report as one document. Download and Share both send this
   (refinement 1, #13: Share used to send only the tab on screen). */
function markdownDocument(
  result: VideoAnalysis,
  sourceMetadata?: SourceMetadata | null,
  completeness: AnalysisCompleteness = "full",
): MarkdownDocument {
  const filename = `${result.title || "videolens-notes"}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
  return {
    filename: filename || "videolens-notes",
    title: result.title || "VideoLens notes",
    text: buildMarkdownReport(result, sourceMetadata, completeness),
  };
}

function formatCount(value: number) {
  return new Intl.NumberFormat("en", { notation: "compact" }).format(value);
}

export function creatorInitials(name: string) {
  return name
    .replace(/^@/, "")
    .trim()
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

function formatUploadDate(value: string) {
  if (!/^\d{8}$/.test(value)) return value;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6)) - 1;
  const day = Number(value.slice(6, 8));
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(Date.UTC(year, month, day)),
  );
}

/** "2026-10-12"-style machine value for `<time dateTime>`, when the backend
 *  sent the compact yt-dlp form; otherwise the value as given. */
function uploadDateTime(value: string) {
  return /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value;
}

// Official brand glyphs only, sourced from each platform's own brand-resource
// pages (see mem/20260810-official-platform-icons.md). Omitted entirely for
// platforms without a redistribution-friendly logo (e.g. TikTok requires
// prior written permission) - falls back to the plain platform-name text.
const PLATFORM_ICONS: Record<string, string> = {
  instagram: "/brand/instagram-glyph.svg",
  youtube: "/brand/youtube-icon.svg",
};

/**
 * The source card, drawn on design/shots/Results.png: platform chip with the
 * outbound "Original post" link on one row, the creator under a monogram, the
 * caption clamped behind "Show more", then a ruled footer of counts and the
 * posting date. HomeScreen supplies the card surface around it (so the same
 * component also renders bare inside the phone disclosure).
 *
 * The counts lost their icons in the editorial pass: "184K views" says what it
 * is in words, and the glyph beside it was a second label for the same fact.
 */
export function SourceCard({ metadata }: { metadata: SourceMetadata }) {
  /* Third-party strings (yt-dlp read them off the fetched page): linked only
     when they are plain http(s) addresses. */
  const sourceHref = safeHttpUrl(metadata.source_url);
  const uploaderHref = safeHttpUrl(metadata.uploader_url);
  const [expanded, setExpanded] = useState(false);
  const stats = [
    { label: "views", value: metadata.view_count },
    { label: "likes", value: metadata.like_count },
    { label: "comments", value: metadata.comment_count },
  ].flatMap((stat) => (stat.value == null ? [] : [{ ...stat, value: stat.value }]));
  const icon = PLATFORM_ICONS[platformKey(metadata.platform) ?? ""];

  return (
    <article className="source-card">
      <div className="source-card__origin">
        <span className="source-card__platform">
          {icon && (
            <img
              src={icon}
              /* Decorative on purpose: the platform name sits right beside it,
                 so alt text would double-announce. */
              alt=""
              className="source-card__platform-icon"
            />
          )}
          {platformName(metadata.platform)}
        </span>
        {sourceHref && (
          <a href={sourceHref} target="_blank" rel="noreferrer" className="source-card__action">
            Original post
            <ArrowUpRight aria-hidden="true" />
          </a>
        )}
      </div>

      {metadata.uploader && (
        <div className="source-card__creator">
          <span className="source-card__monogram" aria-hidden="true">
            {creatorInitials(metadata.uploader)}
          </span>
          <div className="min-w-0">
            {uploaderHref ? (
              <a
                href={uploaderHref}
                target="_blank"
                rel="noreferrer"
                className="source-card__creator-link"
                title={metadata.uploader}
              >
                {metadata.uploader}
              </a>
            ) : (
              <p className="source-card__creator-name" title={metadata.uploader}>
                {metadata.uploader}
              </p>
            )}
            {metadata.title && metadata.title !== metadata.description && (
              <p className="source-card__source-title">{metadata.title}</p>
            )}
          </div>
        </div>
      )}

      {metadata.description && (
        <p className={`source-card__caption ${expanded ? "" : "line-clamp-4"}`}>{metadata.description}</p>
      )}
      {metadata.description && metadata.description.length > 160 && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          /* self-start because `all: unset` blockifies the button as a flex
             item of `.source-card`, which would otherwise stretch the hit
             target across the whole column. */
          className="disclosure self-start"
          aria-expanded={expanded}
        >
          {expanded ? "Show less" : "Show more"}
          <ChevronDown aria-hidden="true" />
        </button>
      )}

      {(stats.length > 0 || metadata.upload_date) && (
        <footer className="source-card__footer">
          {stats.length > 0 && (
            <ul className="source-card__stats">
              {stats.map((stat) => (
                <li
                  key={stat.label}
                  className="source-card__stat"
                  aria-label={`${stat.value.toLocaleString("en-US")} ${stat.label}`}
                >
                  <strong>{formatCount(stat.value)}</strong> {stat.label}
                </li>
              ))}
            </ul>
          )}
          {metadata.upload_date && (
            <p className="source-card__date">
              Posted{" "}
              <time dateTime={uploadDateTime(metadata.upload_date)}>
                {formatUploadDate(metadata.upload_date)}
              </time>
            </p>
          )}
        </footer>
      )}
    </article>
  );
}

/**
 * The Source card for an uploaded file (refinement 2, #6). A file run has no
 * platform metadata — the server keeps neither the name nor anything about the
 * file beyond its length — so this shows what is honestly known: the name as
 * picked in this browser (from the submit, or the History record) and the
 * duration from the run detail. Either may be missing; the caller renders the
 * card only when at least one is present.
 */
export function FileSourceCard({ name, durationSeconds }: { name: string | null; durationSeconds: number | null }) {
  const duration = formatDuration(durationSeconds);
  const kind = name && /\.mp3$/i.test(name) ? "Audio file" : name && /\.(mp4|mov)$/i.test(name) ? "Video file" : "Uploaded file";
  return (
    <article className="source-card">
      <div className="source-card__origin">
        <span className="source-card__platform">{kind}</span>
      </div>
      {name && (
        <p className="source-card__file-name" title={name}>
          {name}
        </p>
      )}
      {duration && (
        <footer className="source-card__footer">
          <p className="source-card__stat">
            Duration <strong>{duration}</strong>
          </p>
        </footer>
      )}
    </article>
  );
}

/* Rendered inside HomeScreen's `.result-card`, so this returns the card's own
   children rather than another wrapper: title band, completeness note, tab
   row, panels. Nothing in here scrolls on its own — the Analyze band does
   (see app-shell-layout.md), so a long transcript simply makes the page
   longer between the fixed nav and the fixed footer/dock. */
export default function ResultsView({
  result,
  sourceMetadata,
  completeness = "full",
}: {
  result: VideoAnalysis;
  sourceMetadata?: SourceMetadata | null;
  completeness?: AnalysisCompleteness;
}) {
  const captionsOnly = completeness === "captions_only";
  const [active, setActive] = useState<TabKey>(DEFAULT_TAB);
  const summary = splitTakeaway(result.summary);
  const [copied, setCopied] = useState(false);
  const { canShare, share, save } = useResultExport();
  const tabRefs = useRef<Partial<Record<TabKey, HTMLButtonElement | null>>>({});

  const content = result[active];

  /* The copied tick belongs to the tab it copied. Reset where the tab changes
     rather than in an effect watching `active` — same behaviour, one render
     fewer, and no set-state-in-effect. */
  const selectTab = (key: TabKey) => {
    setActive(key);
    setCopied(false);
    /* A tab half under the edge fade comes fully into view once chosen. */
    tabRefs.current[key]?.scrollIntoView({ block: "nearest", inline: "nearest" });
  };

  /* Refinement 11 (D-R10-2): with large text on a narrow phone the four tabs
     do not fit, and a scroller with a hidden scrollbar just cut "Transcript"
     off mid-word, which read as broken. The row still scrolls, but now says
     so: an edge fade with a chevron appears on whichever side has more, and
     tapping it pages the row. The state is written straight onto the
     wrapper's data attributes (no React state, so no re-render per scroll
     event); CSS shows the chevrons from those. */
  const scrollerCleanup = useRef<(() => void) | null>(null);
  const tabScroller = useCallback((wrap: HTMLDivElement | null) => {
    scrollerCleanup.current?.();
    scrollerCleanup.current = null;
    const list = wrap?.querySelector<HTMLElement>(".tab-list");
    if (!wrap || !list) return;
    const update = () => {
      const max = list.scrollWidth - list.clientWidth;
      /* scrollLeft is negative in an RTL row; the row here is always LTR. */
      wrap.dataset.moreStart = String(list.scrollLeft > 1);
      wrap.dataset.moreEnd = String(max - list.scrollLeft > 1);
    };
    update();
    list.addEventListener("scroll", update, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(list);
    scrollerCleanup.current = () => {
      list.removeEventListener("scroll", update);
      observer?.disconnect();
    };
  }, []);
  const pageTabs = (direction: 1 | -1) => (event: { currentTarget: HTMLElement }) => {
    const list = event.currentTarget.parentElement?.querySelector<HTMLElement>(".tab-list");
    list?.scrollBy({ left: direction * list.clientWidth * 0.7, behavior: "smooth" });
  };

  /* WAI-ARIA tabs, automatic activation: arrows move and select, Home/End jump
     to the ends, and only the selected tab is in the Tab order (roving
     tabindex), so Tab from the row goes straight into the panel. */
  const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = TABS.findIndex((tab) => tab.key === active);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = TABS.length - 1;
    else return;
    event.preventDefault();
    const key = TABS[next].key;
    selectTab(key);
    tabRefs.current[key]?.focus();
  };

  /* Copy stays per tab: it is the quick "grab this transcript" action, and
     its label says so ("Copy transcript"). Share and Download are the whole
     report, and Share's label says that ("Share all results"). */
  const copyNoun = COPY_NOUN[active];
  const copyLabel = `Copy ${copyNoun}`;
  const copiedLabel = `${capitalise(copyNoun)} copied`;
  const copyContent = async () => {
    try {
      await navigator.clipboard.writeText(content);
    } catch {
      return; /* no clipboard permission: no tick, nothing claimed */
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  const shareContent = () => share(markdownDocument(result, sourceMetadata, completeness));

  return (
    <>
      {/* Copy acts on whichever tab is showing; Share and Download are the
          whole report regardless of tab (refinement 1). All three sit in the title band, as drawn —
          the download used to live under the last panel, where it read as part
          of that panel and was a long scroll away on a full transcript. */}
      <div className="result-head">
        <h2 className="result-title" dir="auto">
          {result.title}
        </h2>
        <div className="result-actions">
          <span className="copy-wrap">
            <button
              type="button"
              onClick={copyContent}
              className="icon-action"
              data-state={copied ? "copied" : undefined}
              aria-label={copied ? copiedLabel : copyLabel}
              title={copied ? copiedLabel : copyLabel}
            >
              {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
            </button>
            {/* The visible half of the confirmation: a touch screen has no
                tooltip, and a bare tick does not say *what* was copied. A
                small label under the button for the tick's two seconds,
                positioned so nothing moves. The live region is separate and
                always mounted, so the announcement is not lost. */}
            {copied && (
              <span className="copy-flash" aria-hidden="true">
                {copiedLabel}
              </span>
            )}
            <span className="sr-only" role="status">
              {copied ? `${copiedLabel} to the clipboard.` : ""}
            </span>
          </span>
          {canShare && (
            <button
              type="button"
              onClick={() => void shareContent()}
              className="icon-action"
              aria-label="Share all results"
              title="Share all results"
            >
              <Share2 aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            onClick={() => void save(markdownDocument(result, sourceMetadata, completeness))}
            className="btn btn-primary btn-pill result-download"
          >
            Download .md
          </button>
        </div>
      </div>

      {/* Between the title and the tabs on purpose: it qualifies all four
          panels, so it belongs to none of them. Nothing renders at all on a
          `full` run — the normal path stays exactly as drawn, the same
          restraint the capability strip applies when the deployment is
          healthy.

          A plain <p>, not role="alert" and not a live region: the run
          succeeded. This is a qualifier arriving with brand-new content the
          user has just navigated to, and read in order it lands right after
          the title — announcing it as an error would be both wrong and louder
          than the fact deserves. */}
      {captionsOnly && (
        <p className="completeness-note">
          <strong>{CAPTIONS_ONLY_LEAD}</strong> {CAPTIONS_ONLY_BODY}
        </p>
      )}

      <div className="tab-scroller" ref={tabScroller} data-more-start="false" data-more-end="false">
        {/* The chevrons are pointer-only helpers (aria-hidden, out of the Tab
            order): keyboard users already move through the row with the arrow
            keys, and focusing a tab scrolls it into view. */}
        <button
          type="button"
          className="tab-more tab-more--start"
          aria-hidden="true"
          tabIndex={-1}
          onClick={pageTabs(-1)}
        >
          <ChevronLeft aria-hidden="true" />
        </button>
        <button
          type="button"
          className="tab-more tab-more--end"
          aria-hidden="true"
          tabIndex={-1}
          onClick={pageTabs(1)}
        >
          <ChevronRight aria-hidden="true" />
        </button>
        <div className="tab-list" role="tablist" aria-label="Analysis results" onKeyDown={onTabKeyDown}>
          {TABS.map((tab) => (
            <button
              key={tab.key}
              ref={(node) => {
                tabRefs.current[tab.key] = node;
              }}
              type="button"
              onClick={() => selectTab(tab.key)}
              role="tab"
              id={`result-tab-${tab.key}`}
              aria-selected={active === tab.key}
              aria-controls={`result-panel-${tab.key}`}
              tabIndex={active === tab.key ? 0 : -1}
              className="tab"
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* All four panels stay mounted; `.panel` hides the inactive ones with
          `display: none`, which also keeps them out of the a11y tree, and
          `[data-active="true"]` drives the fade-in. Mounted, not remounted, is
          also what keeps a transcript search alive across a tab switch. */}
      <div
        className="panel"
        data-active={active === "markdown" ? "true" : "false"}
        role="tabpanel"
        id="result-panel-markdown"
        aria-labelledby="result-tab-markdown"
        tabIndex={0}
      >
        <div className="prose-serif">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              /* The card title above is the h2; the notes' own headings step
                 down beneath it whatever level the model wrote them at, so
                 the outline stays one document. */
              h1: ({ children }) => (
                <h3 className="notes-h1" dir="auto">
                  {children}
                </h3>
              ),
              h2: ({ children }) => <h3 dir="auto">{children}</h3>,
              h3: ({ children }) => <h4 dir="auto">{children}</h4>,
              h4: ({ children }) => <h5 dir="auto">{children}</h5>,
              /* Refinement 6 (RES-14): every block the notes can produce
                 takes its direction from its own first strong character, so
                 an Arabic or Hebrew note aligns right (and its list markers
                 sit on the right) while an English one in the same run does
                 not. Only the props each element uses are passed on (react-markdown
                 also hands over `node`, which is not a DOM attribute). */
              p: ({ children }) => <p dir="auto">{children}</p>,
              ul: ({ children, className }) => (
                <ul dir="auto" className={className}>
                  {children}
                </ul>
              ),
              ol: ({ children, className, start }) => (
                <ol dir="auto" className={className} start={start}>
                  {children}
                </ol>
              ),
              li: ({ children, className }) => (
                <li dir="auto" className={className}>
                  {children}
                </li>
              ),
              blockquote: ({ children }) => <blockquote dir="auto">{children}</blockquote>,
              /* `style` carries a GFM column's alignment (`:--:`). */
              th: ({ children, style }) => (
                <th dir="auto" style={style}>
                  {children}
                </th>
              ),
              td: ({ children, style }) => (
                <td dir="auto" style={style}>
                  {children}
                </td>
              ),
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noreferrer" className="text-link">
                  {children}
                </a>
              ),
              table: ({ children }) => (
                <div className="notes-table">
                  <table>{children}</table>
                </div>
              ),
            }}
          >
            {result.markdown}
          </ReactMarkdown>
        </div>
      </div>

      <div
        className="panel"
        data-active={active === "summary" ? "true" : "false"}
        role="tabpanel"
        id="result-panel-summary"
        aria-labelledby="result-tab-summary"
        tabIndex={0}
      >
        {summary.takeaway ? (
          <div className="prose-serif">
            <figure className="takeaway">
              <figcaption className="takeaway-label">Key takeaway</figcaption>
              <p className="takeaway-text break-words" dir="auto">
                {summary.takeaway}
              </p>
            </figure>
            {summary.rest ? (
              <p className="whitespace-pre-wrap break-words" dir="auto">
                {summary.rest}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="prose-serif">No summary was generated.</p>
        )}
      </div>

      <div
        className="panel"
        data-active={active === "transcript" ? "true" : "false"}
        role="tabpanel"
        id="result-panel-transcript"
        aria-labelledby="result-tab-transcript"
      >
        <TranscriptView segments={result.transcript_segments || []} fallback={result.transcript} />
      </div>

      <div
        className="panel"
        data-active={active === "screen_text" ? "true" : "false"}
        role="tabpanel"
        id="result-panel-screen_text"
        aria-labelledby="result-tab-screen_text"
        tabIndex={0}
      >
        {/* The one place the caption-only run actively lies if left alone:
            an empty section under a tab called "On-screen" reads as "the
            video had none". `screen_text` is empty here because the caption
            instruction forbids describing visuals the model cannot see, not
            because anything was searched and came up empty. */}
        <OnScreenView
          segments={result.screen_text_segments || []}
          fallback={result.screen_text || ""}
          emptyMessage={captionsOnly ? CAPTIONS_ONLY_NO_SCREEN_TEXT : FULL_NO_SCREEN_TEXT}
        />
      </div>
    </>
  );
}
