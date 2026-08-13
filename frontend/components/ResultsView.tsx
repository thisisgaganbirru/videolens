"use client";

import { useEffect, useState } from "react";
import { Capacitor } from "@capacitor/core";
import { Share } from "@capacitor/share";
import {
  CalendarDays,
  Check,
  ChevronDown,
  Copy,
  Download,
  ExternalLink,
  Eye,
  Heart,
  MessageCircle,
  Share2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ScreenTextSegment, SourceMetadata, TranscriptSegment, VideoAnalysis } from "@/domain/entities";

const TABS = [
  { key: "markdown", label: "Notes" },
  { key: "summary", label: "Summary" },
  { key: "transcript", label: "Transcript" },
  { key: "screen_text", label: "On-screen text" },
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

function TimelineView({
  segments,
  fallback,
  emptyMessage,
}: {
  segments: TimelineSegment[];
  fallback: string;
  emptyMessage: string;
}) {
  if (segments.length === 0) {
    return (
      <div className="mx-auto max-h-[36rem] max-w-prose overflow-y-auto whitespace-pre-wrap text-base leading-7 text-[var(--color-text)] lg:max-h-none lg:min-h-0 lg:flex-1">
        {fallback || emptyMessage}
      </div>
    );
  }

  return (
    <ol
      className="mx-auto max-h-[36rem] max-w-prose overflow-y-auto pr-1 lg:max-h-none lg:min-h-0 lg:flex-1"
      aria-label="Timestamped media timeline"
    >
      {segments.map((segment, index) => {
        const speaker = "speaker" in segment ? segment.speaker : null;
        const isLast = index === segments.length - 1;

        return (
          <li
            key={`${segment.start_seconds}-${segment.end_seconds}-${index}`}
            className={`relative grid grid-cols-[3.5rem_0.75rem_minmax(0,1fr)] gap-2 sm:grid-cols-[4.75rem_1rem_minmax(0,1fr)] sm:gap-3 ${
              isLast ? "" : "pb-6"
            }`}
          >
            <time className="pt-0.5 text-xs font-medium tabular-nums text-[var(--color-muted)]">
              {formatTimestamp(segment.start_seconds)}
              <span className="block text-[var(--color-faint)]">{formatTimestamp(segment.end_seconds)}</span>
            </time>
            <span className="relative flex justify-center" aria-hidden="true">
              <span className="mt-1.5 h-2 w-2 rounded-full border border-[var(--color-muted)] bg-[var(--color-paper-2)]" />
              {!isLast && (
                <span className="absolute bottom-[-1.5rem] top-3 border-l border-[var(--color-rule-strong)]" />
              )}
            </span>
            <div className="min-w-0 pb-1">
              {speaker && (
                <p className="mb-1 break-words text-xs font-semibold uppercase text-[var(--color-muted)]">{speaker}</p>
              )}
              <p className="whitespace-pre-wrap break-words text-base leading-7 text-[var(--color-text)]">{segment.text}</p>
            </div>
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

function buildMarkdownReport(result: VideoAnalysis, sourceMetadata?: SourceMetadata | null) {
  const sections = [`# ${singleLine(result.title)}`];

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
      "No on-screen text was detected.",
    )}`,
  );

  return `${sections.join("\n\n")}\n`;
}

function downloadMarkdown(result: VideoAnalysis, sourceMetadata?: SourceMetadata | null) {
  const filename = `${result.title || "videolens-notes"}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");

  const blob = new Blob([buildMarkdownReport(result, sourceMetadata)], { type: "text/markdown;charset=utf-8" });
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

export function SourceCard({ metadata }: { metadata: SourceMetadata }) {
  const [expanded, setExpanded] = useState(false);
  const stats = [
    { label: "views", value: metadata.view_count, icon: Eye },
    { label: "likes", value: metadata.like_count, icon: Heart },
    { label: "comments", value: metadata.comment_count, icon: MessageCircle },
  ].flatMap((stat) => (stat.value == null ? [] : [{ ...stat, value: stat.value }]));

  return (
    <article className="source-card">
      <header className="source-card__header">
        <div className="source-card__origin">
          <span className="source-card__platform">
            {PLATFORM_ICONS[metadata.platform.toLowerCase()] && (
              <img
                src={PLATFORM_ICONS[metadata.platform.toLowerCase()]}
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
            className="source-card__action"
          >
            Original post
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        </div>

        {metadata.uploader &&
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
          </div>}
      </header>

      {metadata.description && (
        <p
          className={`source-card__caption ${expanded ? "" : "line-clamp-3"}`}
        >
          {metadata.description}
        </p>
      )}
      {metadata.description && metadata.description.length > 160 && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="source-card__disclosure"
          aria-expanded={expanded}
        >
          {expanded ? "Show less" : "Show more"}
          <ChevronDown className="source-card__chevron h-4 w-4" aria-hidden="true" />
        </button>
      )}

      {(stats.length > 0 || metadata.upload_date) && (
        <footer className="source-card__footer">
          <ul className="source-card__stats">
          {stats.map((stat) => (
              <li key={stat.label} className="source-card__stat" aria-label={`${stat.value.toLocaleString("en-US")} ${stat.label}`}>
                <stat.icon className="h-4 w-4" aria-hidden="true" />
                <strong>{formatCount(stat.value)}</strong>
                <span>{stat.label}</span>
              </li>
          ))}
          </ul>
          {metadata.upload_date && (
            <time className="source-card__date" dateTime={metadata.upload_date}>
              <CalendarDays className="h-4 w-4" aria-hidden="true" />
              {formatUploadDate(metadata.upload_date)}
            </time>
          )}
        </footer>
      )}
    </article>
  );
}

export default function ResultsView({
  result,
  sourceMetadata,
}: {
  result: VideoAnalysis;
  sourceMetadata?: SourceMetadata | null;
}) {
  const [active, setActive] = useState<TabKey>("markdown");
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
    <section className="flex min-w-0 flex-col gap-5 py-2 sm:py-3 lg:h-full lg:min-h-0 lg:overflow-hidden">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center lg:shrink-0">
        <h2 className="min-w-0 break-words text-xl font-semibold text-[var(--color-text-strong)] sm:text-2xl">{result.title}</h2>
        <button
          type="button"
          onClick={() => downloadMarkdown(result, sourceMetadata)}
          className="button-secondary w-full shrink-0 sm:w-auto"
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          Download report (.md)
        </button>
      </div>

      {/* On desktop this moves into HomeScreen's left sidebar column instead - see app-shell-layout.md */}
      {sourceMetadata && (
        <div className="lg:hidden">
          <SourceCard metadata={sourceMetadata} />
        </div>
      )}

      <div
        className="-mx-1 flex shrink-0 gap-1 overflow-x-auto border-b border-[var(--color-rule)] px-1"
        role="tablist"
        aria-label="Analysis results"
      >
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActive(tab.key)}
            role="tab"
            aria-selected={active === tab.key}
            className="tab-button shrink-0 whitespace-nowrap px-3 py-2"
          >
            {tab.label}
          </button>
        ))}
      </div>

      {active === "markdown" ? (
        <article className="mx-auto max-h-[36rem] max-w-prose overflow-y-auto pr-1 text-base text-[var(--color-text)] lg:max-h-none lg:min-h-0 lg:flex-1">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              h1: ({ children }) => (
                <h1 className="mb-5 break-words text-2xl font-bold leading-tight text-[var(--color-text-strong)]">{children}</h1>
              ),
              h2: ({ children }) => (
                <h2 className="mb-3 mt-8 border-b border-[var(--color-rule)] pb-2 text-xl font-bold text-[var(--color-text-strong)] first:mt-0">
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 className="mb-2 mt-6 text-lg font-semibold text-[var(--color-text-strong)]">{children}</h3>
              ),
              h4: ({ children }) => (
                <h4 className="mb-2 mt-5 text-base font-semibold text-[var(--color-text)]">{children}</h4>
              ),
              p: ({ children }) => <p className="mb-4 leading-7 last:mb-0">{children}</p>,
              ul: ({ children }) => (
                <ul className="mb-5 list-disc space-y-2 pl-6 marker:text-[var(--color-faint)]">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="mb-5 list-decimal space-y-2 pl-6 marker:text-[var(--color-muted)]">{children}</ol>
              ),
              li: ({ children }) => <li className="pl-1 leading-7">{children}</li>,
              strong: ({ children }) => (
                <strong className="font-semibold text-[var(--color-text-strong)]">{children}</strong>
              ),
              blockquote: ({ children }) => (
                <blockquote className="my-5 border-l-2 border-[var(--color-rule-strong)] pl-4 text-[var(--color-muted)]">
                  {children}
                </blockquote>
              ),
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[var(--color-accent-hover)] underline underline-offset-4"
                >
                  {children}
                </a>
              ),
              code: ({ children, className }) => (
                <code
                  className={`${className || ""} rounded bg-[var(--color-paper)] px-1.5 py-0.5 font-mono text-[0.875em] text-[var(--color-text)]`}
                >
                  {children}
                </code>
              ),
              pre: ({ children }) => (
                <pre className="mb-5 overflow-x-auto rounded-[var(--radius-md)] border border-[var(--color-rule)] bg-[var(--color-paper)] p-4 text-sm leading-6 [&_code]:bg-transparent [&_code]:p-0">
                  {children}
                </pre>
              ),
              table: ({ children }) => (
                <table className="mb-5 block w-full overflow-x-auto border-collapse text-left text-sm">
                  {children}
                </table>
              ),
              thead: ({ children }) => <thead className="border-b border-[var(--color-rule-strong)]">{children}</thead>,
              th: ({ children }) => (
                <th className="whitespace-nowrap px-3 py-2 font-semibold text-[var(--color-text-strong)]">{children}</th>
              ),
              td: ({ children }) => (
                <td className="border-b border-[var(--color-rule)] px-3 py-2 align-top leading-6">{children}</td>
              ),
              hr: () => <hr className="my-7 border-[var(--color-rule)]" />,
            }}
          >
            {result.markdown}
          </ReactMarkdown>
        </article>
      ) : active === "transcript" ? (
        <TimelineView
          segments={result.transcript_segments || []}
          fallback={result.transcript}
          emptyMessage="No spoken content was detected."
        />
      ) : active === "screen_text" ? (
        <TimelineView
          segments={result.screen_text_segments || []}
          fallback={result.screen_text}
          emptyMessage="No on-screen text was detected."
        />
      ) : (
        <div className="mx-auto max-h-[36rem] max-w-prose overflow-y-auto whitespace-pre-wrap break-words text-base leading-7 text-[var(--color-text)] lg:max-h-none lg:min-h-0 lg:flex-1">
          {content || "No content was detected."}
        </div>
      )}

      <div className="responsive-actions lg:shrink-0">
        <button
          type="button"
          onClick={copyContent}
          className="button-secondary"
        >
          {copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </button>
        {canShare && (
          <button
            type="button"
            onClick={() => void shareContent()}
            className="button-secondary"
          >
            <Share2 className="h-4 w-4" aria-hidden="true" />
            Share
          </button>
        )}
      </div>
    </section>
  );
}
