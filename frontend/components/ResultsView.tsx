"use client";

import { useEffect, useState } from "react";
import { Capacitor } from "@capacitor/core";
import { Share } from "@capacitor/share";
import {
  CalendarDays,
  Check,
  ChevronDown,
  Copy,
  ExternalLink,
  Eye,
  Heart,
  MessageCircle,
  Share2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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
  { key: "screen_text", label: "On-Screen" },
] as const;

type TabKey = (typeof TABS)[number]["key"];
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
 * Timestamped rows on the shared `.line` grid: an accent timestamp column and
 * the text beside it, separated by hairlines rather than a drawn rail. Only
 * the start time is shown (the end is carried in the `title`/`dateTime`) —
 * the two-line time column the old glass layout used cost more width than the
 * 3.6rem gutter the Terminal grid allows.
 */
function TimelineView({
  segments,
  fallback,
  emptyMessage,
  label,
  marker,
}: {
  segments: TimelineSegment[];
  fallback: string;
  emptyMessage: string;
  label: string;
  marker?: string;
}) {
  if (segments.length === 0) {
    return <p className="prose whitespace-pre-wrap break-words">{fallback || emptyMessage}</p>;
  }

  return (
    <ol className="list-none" aria-label={label}>
      {segments.map((segment, index) => {
        const speaker = "speaker" in segment ? segment.speaker : null;

        return (
          <li key={`${segment.start_seconds}-${segment.end_seconds}-${index}`} className="line">
            <time
              dateTime={`PT${Math.max(0, Math.round(segment.start_seconds))}S`}
              title={`${formatTimestamp(segment.start_seconds)}–${formatTimestamp(segment.end_seconds)}`}
              className="tabular-nums"
            >
              {formatTimestamp(segment.start_seconds)}
            </time>
            <p className="min-w-0 whitespace-pre-wrap break-words">
              {speaker ? <span className="speaker">{speaker}</span> : null}
              {!speaker && marker ? <span className="ocr-tag">{marker}</span> : null}
              {segment.text}
            </p>
          </li>
        );
      })}
    </ol>
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
      `- **Platform:** ${singleLine(sourceMetadata.platform)}`,
      sourceMetadata.title && `- **Source title:** ${singleLine(sourceMetadata.title)}`,
      sourceMetadata.uploader &&
        `- **Creator:** ${
          sourceMetadata.uploader_url
            ? `[${singleLine(sourceMetadata.uploader)}](<${sourceMetadata.uploader_url}>)`
            : singleLine(sourceMetadata.uploader)
        }`,
      sourceMetadata.upload_date && `- **Published:** ${singleLine(sourceMetadata.upload_date)}`,
      sourceMetadata.view_count != null && `- **Views:** ${sourceMetadata.view_count.toLocaleString("en-US")}`,
      sourceMetadata.like_count != null && `- **Likes:** ${sourceMetadata.like_count.toLocaleString("en-US")}`,
      sourceMetadata.comment_count != null &&
        `- **Comments:** ${sourceMetadata.comment_count.toLocaleString("en-US")}`,
      `- **Original post:** <${sourceMetadata.source_url}>`,
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

function downloadMarkdown(
  result: VideoAnalysis,
  sourceMetadata?: SourceMetadata | null,
  completeness: AnalysisCompleteness = "full",
) {
  const filename = `${result.title || "videolens-notes"}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");

  const blob = new Blob([buildMarkdownReport(result, sourceMetadata, completeness)], {
    type: "text/markdown;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${filename || "videolens-notes"}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

function formatCount(value: number) {
  return new Intl.NumberFormat("en", { notation: "compact" }).format(value);
}

function creatorInitials(name: string) {
  return name
    .trim()
    .split(/\s+/)
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

// Official brand glyphs only, sourced from each platform's own brand-resource
// pages (see mem/20260810-official-platform-icons.md). Omitted entirely for
// platforms without a redistribution-friendly logo (e.g. TikTok requires
// prior written permission) - falls back to the plain platform-name text.
const PLATFORM_ICONS: Record<string, string> = {
  instagram: "/brand/instagram-glyph.svg",
  youtube: "/brand/youtube-icon.svg",
};

/**
 * Deliberately unboxed: no border, no tint, no shadow. It sits in HomeScreen's
 * left ruled column, where the single vertical hairline against the results
 * pane is the whole separation — two bordered rectangles side by side read as
 * a slide, which is what the de-boxing pass removed.
 *
 * Section order mirrors the mockup: origin row (platform left, original-post
 * link right), creator block with the source title nested under the uploader,
 * caption clamped to three lines behind a disclosure, then the stats footer.
 */
export function SourceCard({ metadata }: { metadata: SourceMetadata }) {
  const [expanded, setExpanded] = useState(false);
  const stats = [
    { label: "views", value: metadata.view_count, icon: Eye },
    { label: "likes", value: metadata.like_count, icon: Heart },
    { label: "comments", value: metadata.comment_count, icon: MessageCircle },
  ].flatMap((stat) => (stat.value == null ? [] : [{ ...stat, value: stat.value }]));

  return (
    <article className="source-card">
      {/* Row, not a stacked column: platform reads left, the outbound link
          right, on one baseline — the mockup's `.origin`. */}
      <div className="source-card__origin w-full flex-row items-center justify-between gap-[var(--space-xs)]">
        <span className="source-card__platform">
          {PLATFORM_ICONS[metadata.platform.toLowerCase()] && (
            <img
              src={PLATFORM_ICONS[metadata.platform.toLowerCase()]}
              /* Decorative on purpose: the platform name sits right beside it,
                 so alt text would double-announce. */
              alt=""
              className="source-card__platform-icon"
            />
          )}
          {metadata.platform}
        </span>
        <a
          href={metadata.source_url}
          target="_blank"
          rel="noreferrer"
          className="source-card__action hover:text-[var(--color-accent)]"
        >
          original post
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      </div>

      {metadata.uploader && (
        <div className="source-card__creator">
          <span className="source-card__monogram" aria-hidden="true">
            {creatorInitials(metadata.uploader)}
          </span>
          <div className="min-w-0">
            {metadata.uploader_url ? (
              <a
                href={metadata.uploader_url}
                target="_blank"
                rel="noreferrer"
                className="source-card__creator-link hover:text-[var(--color-accent)]"
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
        <p className={`source-card__caption ${expanded ? "" : "line-clamp-3"}`}>{metadata.description}</p>
      )}
      {metadata.description && metadata.description.length > 160 && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          /* The shared `.disclosure` (mockup name), not the BEM
             `.source-card__disclosure`: only the shared rule carries the
             `all: unset` reset, `cursor: pointer`, the svg sizing, and the
             `[aria-expanded="true"] svg` chevron flip the design keys off. */
          /* self-start because `all: unset` blockifies the button as a flex
             item of `.source-card`, which would otherwise stretch the hit
             target across the whole column. */
          className="disclosure self-start hover:text-[var(--color-focus)]"
          aria-expanded={expanded}
        >
          {expanded ? "show less" : "show more"}
          <ChevronDown aria-hidden="true" />
        </button>
      )}

      {(stats.length > 0 || metadata.upload_date) && (
        <footer className="source-card__footer">
          <ul className="source-card__stats">
            {stats.map((stat) => (
              <li
                key={stat.label}
                className="source-card__stat"
                aria-label={`${stat.value.toLocaleString("en-US")} ${stat.label}`}
              >
                <stat.icon className="h-3.5 w-3.5" aria-hidden="true" />
                <strong>{formatCount(stat.value)}</strong>
                <span>{stat.label}</span>
              </li>
            ))}
          </ul>
          {metadata.upload_date && (
            <time className="source-card__date" dateTime={metadata.upload_date}>
              <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
              {formatUploadDate(metadata.upload_date)}
            </time>
          )}
        </footer>
      )}
    </article>
  );
}

/* Rendered inside HomeScreen's `.results` flex column, so this returns the
   pane's own children rather than another wrapper: title band, `.tab-list`
   (inset to the pane gutter, underline spanning the full tint), then the
   scrolling `.pane`. */
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
  const [active, setActive] = useState<TabKey>("summary");
  const [copied, setCopied] = useState(false);
  const [canShare, setCanShare] = useState(false);

  const content = result[active];

  useEffect(() => {
    setCopied(false);
  }, [active]);

  useEffect(() => {
    setCanShare(Capacitor.isNativePlatform() || typeof navigator.share === "function");
  }, []);

  const copyContent = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  const shareContent = async () => {
    if (Capacitor.isNativePlatform()) {
      await Share.share({ title: result.title, text: content, dialogTitle: "Share analysis" });
    } else if (navigator.share) {
      await navigator.share({ title: result.title, text: content });
    }
  };

  return (
    <>
      {/* Copy and share sit up here rather than in `.actions` below: they act
          on whichever tab is showing, so they belong with the title band that
          spans all four tabs, not stacked under the panel content where they
          read as part of the last panel. Download stays below — it produces
          one whole-report file regardless of the active tab. */}
      <div className="result-head">
        <h2 className="min-w-0 break-words text-[0.95rem] font-semibold leading-[1.35] text-[var(--color-ink)]">
          {result.title}
        </h2>
        <div className="result-actions">
          <button
            type="button"
            onClick={copyContent}
            className="icon-action"
            data-state={copied ? "copied" : undefined}
            aria-label={copied ? "Copied to clipboard" : "Copy this tab"}
            title={copied ? "copied" : "copy"}
          >
            {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          </button>
          {canShare && (
            <button
              type="button"
              onClick={() => void shareContent()}
              className="icon-action"
              aria-label="Share this tab"
              title="share"
            >
              <Share2 aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      {/* A sibling of `.result-head`, above `.tab-list`, on purpose: it
          qualifies all four panels, so it belongs to the pane's fixed header
          rather than to any one of them, and in the `fixed` frame that header
          is the part that does not scroll away. It stays *outside* the title
          band rather than inside it — that band is a two-column row (title
          left, copy/share right), and a full-width note has no column there. Nothing renders at all on a `full` run — the
          normal path must be pixel-identical to before, the same restraint the
          capability strip applies when the deployment is healthy.

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

      <div className="tab-list" role="tablist" aria-label="Analysis results">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActive(tab.key)}
            role="tab"
            id={`result-tab-${tab.key}`}
            aria-selected={active === tab.key}
            aria-controls={`result-panel-${tab.key}`}
            className="tab"
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="pane">
        {/* All four panels stay mounted; `.panel` hides the inactive ones with
            `display: none`, which also keeps them out of the a11y tree, and
            `[data-active="true"]` drives the fade-in. */}
        <div
          className="panel"
          data-active={active === "markdown" ? "true" : "false"}
          role="tabpanel"
          id="result-panel-markdown"
          aria-labelledby="result-tab-markdown"
        >
          <div className="prose">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => (
                  <h1 className="mb-[var(--space-sm)] break-words text-[1.15rem] font-bold leading-[1.3] text-[var(--color-ink)]">
                    {children}
                  </h1>
                ),
                h2: ({ children }) => (
                  <h2 className="mb-[var(--space-xs)] mt-[var(--space-lg)] border-b border-[var(--color-rule)] pb-[var(--space-2xs)] text-[1rem] font-bold text-[var(--color-ink)] first:mt-0">
                    {children}
                  </h2>
                ),
                h3: ({ children }) => (
                  <h3 className="mb-[var(--space-2xs)] mt-[var(--space-md)] text-[0.92rem] font-semibold text-[var(--color-ink)]">
                    {children}
                  </h3>
                ),
                h4: ({ children }) => (
                  <h4 className="mb-[var(--space-2xs)] mt-[var(--space-sm)] text-[0.86rem] font-semibold text-[var(--color-ink-2)]">
                    {children}
                  </h4>
                ),
                p: ({ children }) => <p className="mb-[var(--space-sm)] last:mb-0">{children}</p>,
                ul: ({ children }) => (
                  <ul className="mb-[var(--space-sm)] list-disc space-y-[0.35rem] pl-[1.4rem] marker:text-[var(--color-muted)]">
                    {children}
                  </ul>
                ),
                ol: ({ children }) => (
                  <ol className="mb-[var(--space-sm)] list-decimal space-y-[0.35rem] pl-[1.4rem] marker:text-[var(--color-muted)]">
                    {children}
                  </ol>
                ),
                li: ({ children }) => <li className="pl-1">{children}</li>,
                strong: ({ children }) => (
                  <strong className="font-semibold text-[var(--color-ink)]">{children}</strong>
                ),
                blockquote: ({ children }) => (
                  <blockquote className="my-[var(--space-sm)] border-l-2 border-[var(--color-accent)] pl-[var(--space-sm)] text-[var(--color-muted)]">
                    {children}
                  </blockquote>
                ),
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[var(--color-accent)] underline underline-offset-4 hover:text-[var(--color-focus)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)]"
                  >
                    {children}
                  </a>
                ),
                code: ({ children, className }) => (
                  <code
                    className={`${className || ""} bg-[var(--color-paper-3)] px-1.5 py-0.5 text-[0.9em] text-[var(--color-ink)]`}
                  >
                    {children}
                  </code>
                ),
                pre: ({ children }) => (
                  <pre className="mb-[var(--space-sm)] overflow-x-auto border border-[var(--color-rule)] bg-[var(--color-paper)] p-[var(--space-sm)] text-[0.78rem] leading-[1.55] [&_code]:bg-transparent [&_code]:p-0">
                    {children}
                  </pre>
                ),
                table: ({ children }) => (
                  <table className="mb-[var(--space-sm)] block w-full overflow-x-auto border-collapse text-left text-[0.78rem]">
                    {children}
                  </table>
                ),
                thead: ({ children }) => (
                  <thead className="border-b border-[var(--color-rule-2)]">{children}</thead>
                ),
                th: ({ children }) => (
                  <th className="whitespace-nowrap px-[var(--space-2xs)] py-[0.35rem] font-semibold text-[var(--color-ink)]">
                    {children}
                  </th>
                ),
                td: ({ children }) => (
                  <td className="border-b border-[var(--color-rule)] px-[var(--space-2xs)] py-[0.35rem] align-top">
                    {children}
                  </td>
                ),
                hr: () => <hr className="my-[var(--space-md)] border-[var(--color-rule)]" />,
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
        >
          <p className="prose whitespace-pre-wrap break-words">
            {result.summary || "No summary was generated."}
          </p>
        </div>

        <div
          className="panel"
          data-active={active === "transcript" ? "true" : "false"}
          role="tabpanel"
          id="result-panel-transcript"
          aria-labelledby="result-tab-transcript"
        >
          <TimelineView
            segments={result.transcript_segments || []}
            fallback={result.transcript}
            emptyMessage="No spoken content was detected."
            label="Timestamped transcript"
          />
        </div>

        <div
          className="panel"
          data-active={active === "screen_text" ? "true" : "false"}
          role="tabpanel"
          id="result-panel-screen_text"
          aria-labelledby="result-tab-screen_text"
        >
          {/* The one place the caption-only run actively lies if left alone:
              an empty section under a tab called "On-Screen" reads as "the
              video had none". `screen_text` is empty here because the caption
              instruction forbids describing visuals the model cannot see, not
              because anything was searched and came up empty. */}
          <TimelineView
            segments={result.screen_text_segments || []}
            fallback={result.screen_text}
            emptyMessage={captionsOnly ? CAPTIONS_ONLY_NO_SCREEN_TEXT : FULL_NO_SCREEN_TEXT}
            label="Timestamped on-screen text"
            marker="on-screen"
          />
        </div>

        <div className="actions">
          <button
            type="button"
            onClick={() => downloadMarkdown(result, sourceMetadata, completeness)}
            className="btn btn-secondary"
          >
            download report (.md)
          </button>
        </div>
      </div>
    </>
  );
}
