"use client";

import { useEffect, useState } from "react";
import { ExternalLink, History as HistoryIcon, KeyRound, Menu, ScrollText, X } from "lucide-react";
import { ApiError, getStoredGeminiApiKey, listRuns, setStoredGeminiApiKey } from "@/lib/api";
import { fetchVersionLog, type VersionLogEntry } from "@/lib/versionLog";
import type { RunSummary } from "@/lib/types";

type Tab = "api-key" | "history" | "version-log";

const TABS: { id: Tab; label: string; icon: typeof KeyRound }[] = [
  { id: "api-key", label: "API key", icon: KeyRound },
  { id: "history", label: "History", icon: HistoryIcon },
  { id: "version-log", label: "Version log", icon: ScrollText },
];

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function ApiKeyPanel() {
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setValue(getStoredGeminiApiKey());
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-slate-400">
        Optional. Paste your own Gemini API key to use your own quota instead of the shared one -
        it stays on this device and is only sent with your own requests.
      </p>
      <a
        href="https://aistudio.google.com/apikey"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 self-start text-sm text-indigo-300 hover:underline"
      >
        Get a key from Google AI Studio
        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
      </a>
      <input
        type="password"
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          setSaved(false);
        }}
        placeholder="Paste your Gemini API key"
        autoComplete="off"
        spellCheck={false}
        className="rounded-lg border border-[#343a36] bg-[#0b0d0c] px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-indigo-400"
      />
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => {
            setStoredGeminiApiKey(value);
            setSaved(true);
          }}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium hover:bg-indigo-500"
        >
          Save
        </button>
        <button
          type="button"
          onClick={() => {
            setValue("");
            setStoredGeminiApiKey("");
            setSaved(true);
          }}
          className="rounded-lg border border-[#343a36] px-3 py-1.5 text-sm text-slate-300 hover:bg-[#1b201d]"
        >
          Clear
        </button>
      </div>
      {saved && <p className="text-xs text-slate-500">Saved on this device.</p>}
    </div>
  );
}

function HistoryPanel({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRuns()
      .then((response) => setRuns(response.runs))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load history."));
  }, []);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (runs === null) return <p className="text-sm text-slate-500">Loading...</p>;
  if (runs.length === 0) return <p className="text-sm text-slate-500">No previous runs yet.</p>;

  return (
    <ul className="flex flex-col divide-y divide-[#292e2b]">
      {runs.map((run) => (
        <li key={run.run_id}>
          <button
            type="button"
            onClick={() => onOpenRun(run.run_id)}
            className="flex w-full flex-col items-start gap-0.5 py-3 text-left hover:text-slate-100"
          >
            <span className="truncate text-sm font-medium text-slate-200">
              {run.title || (run.status === "failed" ? "Failed run" : "Untitled run")}
            </span>
            <span className="text-xs text-slate-500">
              {formatDate(run.created_at)} &middot; {run.status}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function VersionLogPanel() {
  const [entries, setEntries] = useState<VersionLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchVersionLog()
      .then(setEntries)
      .catch(() => setError("Could not load the version log."));
  }, []);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (entries === null) return <p className="text-sm text-slate-500">Loading...</p>;
  if (entries.length === 0) return <p className="text-sm text-slate-500">No releases yet.</p>;

  return (
    <ul className="flex flex-col divide-y divide-[#292e2b]">
      {entries.map((entry) => (
        <li key={entry.tag} className="py-3">
          <a
            href={entry.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex flex-col gap-0.5 hover:text-slate-100"
          >
            <span className="text-sm font-medium text-slate-200">{entry.name}</span>
            <span className="text-xs text-slate-500">{formatDate(entry.publishedAt)}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

export default function AppMenu({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("api-key");

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open menu"
        className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-[#343a36] text-slate-300 hover:bg-[#1b201d] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
      >
        <Menu className="h-5 w-5" aria-hidden="true" />
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div className="relative flex h-full w-full max-w-sm flex-col bg-[#121513] shadow-[0_0_60px_rgba(0,0,0,0.4)]">
            <div className="flex items-center justify-between border-b border-[#292e2b] px-4 py-3">
              <h2 className="text-sm font-semibold text-slate-100">Menu</h2>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close menu"
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-[#1b201d] hover:text-slate-100"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>

            <div className="flex border-b border-[#292e2b]" role="tablist">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={tab === id}
                  onClick={() => setTab(id)}
                  className={`flex flex-1 flex-col items-center gap-1 border-b-2 px-2 py-3 text-xs font-medium ${
                    tab === id
                      ? "border-indigo-400 text-slate-100"
                      : "border-transparent text-slate-500 hover:text-slate-300"
                  }`}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  {label}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              {tab === "api-key" && <ApiKeyPanel />}
              {tab === "history" && (
                <HistoryPanel
                  onOpenRun={(runId) => {
                    onOpenRun(runId);
                    setOpen(false);
                  }}
                />
              )}
              {tab === "version-log" && <VersionLogPanel />}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
