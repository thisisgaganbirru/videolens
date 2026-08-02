"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Download } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ScreenTextSegment, TranscriptSegment, VideoAnalysis } from "@/lib/types";

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
      <div className="max-h-[36rem] overflow-y-auto whitespace-pre-wrap text-sm leading-7 text-slate-300">
        {fallback || emptyMessage}
      </div>
    );
  }

  return (
    <ol className="max-h-[36rem] overflow-y-auto pr-1" aria-label="Timestamped media timeline">
      {segments.map((segment, index) => {
        const speaker = "speaker" in segment ? segment.speaker : null;
        const isLast = index === segments.length - 1;

        return (
          <li
            key={`${segment.start_seconds}-${segment.end_seconds}-${index}`}
            className={`relative grid grid-cols-[4.75rem_1rem_minmax(0,1fr)] gap-3 ${
              isLast ? "" : "pb-6"
            }`}
          >
            <time className="pt-0.5 text-xs font-medium tabular-nums text-slate-400">
              {formatTimestamp(segment.start_seconds)}
              <span className="block text-slate-600">{formatTimestamp(segment.end_seconds)}</span>
            </time>
            <span className="relative flex justify-center" aria-hidden="true">
              <span className="mt-1.5 h-2 w-2 rounded-full border border-slate-400 bg-[#121513]" />
              {!isLast && (
                <span className="absolute bottom-[-1.5rem] top-3 border-l border-slate-700" />
              )}
            </span>
            <div className="min-w-0 pb-1">
              {speaker && (
                <p className="mb-1 text-xs font-semibold uppercase text-slate-400">{speaker}</p>
              )}
              <p className="whitespace-pre-wrap text-sm leading-7 text-slate-200">{segment.text}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function downloadMarkdown(result: VideoAnalysis) {
  const filename = `${result.title || "videolens-notes"}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");

  const blob = new Blob([result.markdown], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${filename || "videolens-notes"}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

export default function ResultsView({ result }: { result: VideoAnalysis }) {
  const [active, setActive] = useState<TabKey>("markdown");
  const [copied, setCopied] = useState(false);

  const content = result[active];

  useEffect(() => {
    setCopied(false);
  }, [active]);

  const copyContent = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="flex flex-col gap-5 rounded-lg border border-[#292e2b] bg-[#121513] p-5 shadow-[0_18px_55px_rgba(0,0,0,0.24)] sm:p-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <h2 className="min-w-0 text-xl font-semibold text-slate-100">{result.title}</h2>
        <button
          type="button"
          onClick={() => downloadMarkdown(result)}
          className="inline-flex min-h-11 shrink-0 items-center gap-2 whitespace-nowrap rounded-lg border border-[#343a36] px-3 text-sm text-slate-300 transition-colors hover:bg-[#1b201d] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400 active:bg-[#090b0a]"
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          Download .md
        </button>
      </div>

      <div className="flex gap-1 overflow-x-auto border-b border-[#292e2b]" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActive(tab.key)}
            role="tab"
            aria-selected={active === tab.key}
            className={`min-h-11 shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-indigo-400 ${
              active === tab.key
                ? "border-b-2 border-indigo-400 text-indigo-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {active === "markdown" ? (
        <article className="max-h-[36rem] overflow-y-auto pr-1 text-slate-300">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              h1: ({ children }) => (
                <h1 className="mb-5 text-2xl font-bold leading-tight text-slate-100">{children}</h1>
              ),
              h2: ({ children }) => (
                <h2 className="mb-3 mt-8 border-b border-[#292e2b] pb-2 text-xl font-bold text-slate-100 first:mt-0">
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 className="mb-2 mt-6 text-lg font-semibold text-slate-100">{children}</h3>
              ),
              h4: ({ children }) => (
                <h4 className="mb-2 mt-5 text-base font-semibold text-slate-200">{children}</h4>
              ),
              p: ({ children }) => <p className="mb-4 leading-7 last:mb-0">{children}</p>,
              ul: ({ children }) => (
                <ul className="mb-5 list-disc space-y-2 pl-6 marker:text-slate-500">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="mb-5 list-decimal space-y-2 pl-6 marker:text-slate-400">{children}</ol>
              ),
              li: ({ children }) => <li className="pl-1 leading-7">{children}</li>,
              strong: ({ children }) => (
                <strong className="font-semibold text-slate-100">{children}</strong>
              ),
              blockquote: ({ children }) => (
                <blockquote className="my-5 border-l-2 border-slate-500 pl-4 text-slate-400">
                  {children}
                </blockquote>
              ),
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="text-indigo-300 underline decoration-indigo-500/60 underline-offset-4 hover:text-indigo-200"
                >
                  {children}
                </a>
              ),
              code: ({ children, className }) => (
                <code
                  className={`${className || ""} rounded bg-[#090b0a] px-1.5 py-0.5 font-mono text-[0.875em] text-slate-200`}
                >
                  {children}
                </code>
              ),
              pre: ({ children }) => (
                <pre className="mb-5 overflow-x-auto rounded-lg border border-[#292e2b] bg-[#090b0a] p-4 text-sm leading-6 [&_code]:bg-transparent [&_code]:p-0">
                  {children}
                </pre>
              ),
              table: ({ children }) => (
                <table className="mb-5 block w-full overflow-x-auto border-collapse text-left text-sm">
                  {children}
                </table>
              ),
              thead: ({ children }) => <thead className="border-b border-slate-600">{children}</thead>,
              th: ({ children }) => (
                <th className="whitespace-nowrap px-3 py-2 font-semibold text-slate-100">{children}</th>
              ),
              td: ({ children }) => (
                <td className="border-b border-[#292e2b] px-3 py-2 align-top leading-6">{children}</td>
              ),
              hr: () => <hr className="my-7 border-[#292e2b]" />,
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
        <div className="max-h-[36rem] overflow-y-auto whitespace-pre-wrap text-sm leading-7 text-slate-300">
          {content || "No content was detected."}
        </div>
      )}

      <button
        type="button"
        onClick={copyContent}
        className="inline-flex min-h-11 items-center gap-2 self-start whitespace-nowrap rounded-lg border border-[#343a36] px-3 text-sm text-slate-300 transition-colors hover:bg-[#1b201d] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400 active:bg-[#090b0a]"
      >
        {copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
        {copied ? "Copied" : "Copy"}
      </button>
    </section>
  );
}
