"use client";

import { useState } from "react";
import type { VideoAnalysis } from "@/lib/types";

const TABS = [
  { key: "markdown", label: "Notes" },
  { key: "summary", label: "Summary" },
  { key: "transcript", label: "Transcript" },
  { key: "screen_text", label: "On-screen text" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function ResultsView({ result }: { result: VideoAnalysis }) {
  const [active, setActive] = useState<TabKey>("markdown");

  const content = result[active];

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-slate-800 bg-slate-900 p-6">
      <h2 className="text-xl font-semibold">{result.title}</h2>

      <div className="flex gap-2 border-b border-slate-800">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActive(tab.key)}
            className={`px-3 py-2 text-sm font-medium ${
              active === tab.key
                ? "border-b-2 border-indigo-400 text-indigo-300"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap text-sm text-slate-200">
        {content}
      </pre>

      <button
        type="button"
        onClick={() => navigator.clipboard.writeText(content)}
        className="self-start rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
      >
        Copy
      </button>
    </div>
  );
}
