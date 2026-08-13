"use client";

import { useState } from "react";
import { Film, History as HistoryIcon, KeyRound, Palette, ScrollText, Sparkles } from "lucide-react";
import UploadForm from "@/components/UploadForm";
import RunStatusView from "@/components/RunStatusView";
import ResultsView, { SourceCard } from "@/components/ResultsView";
import { BackgroundPickerPanel } from "@/components/ui/BackgroundSwitcher";
import ApiKeyPanel from "@/components/panels/ApiKeyPanel";
import HistoryPanel from "@/components/panels/HistoryPanel";
import VersionLogPanel from "@/components/panels/VersionLogPanel";
import { useAnalysisRun } from "@/application/useAnalysisRun";

type MainTab = "analyze" | "theme" | "history" | "api-key" | "releases";

const NAV_TABS: { id: MainTab; label: string; icon: typeof Film }[] = [
  { id: "analyze", label: "Analyze", icon: Film },
  { id: "theme", label: "Theme", icon: Palette },
  { id: "history", label: "History", icon: HistoryIcon },
  { id: "api-key", label: "API Key", icon: KeyRound },
  { id: "releases", label: "Releases", icon: ScrollText },
];

export default function HomeScreen() {
  const [activeTab, setActiveTab] = useState<MainTab>("analyze");
  const { status, stage, sourceKind, result, sourceMetadata, error, submit, reset, openRun } = useAnalysisRun();

  const handleOpenRun = (runId: string) => {
    setActiveTab("analyze");
    void openRun(runId);
  };

  return (
    <div className="flex h-[100dvh] w-full items-center justify-center p-3 sm:p-5 md:p-6 overflow-hidden">
      {/* Center Unified Glass Workspace Card */}
      <main className="surface-panel flex h-full max-h-[94dvh] w-full max-w-4xl flex-col overflow-hidden shadow-2xl backdrop-blur-2xl lg:max-h-[97dvh] lg:max-w-6xl xl:max-w-7xl">
        {/* Header Bar & Segmented Navigation inside Center Card */}
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--color-rule)] px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-accent-soft)] border border-[var(--color-accent)] shadow-sm">
              <Sparkles className="h-4 w-4 text-[var(--color-accent)]" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-[var(--color-text-strong)] sm:text-xl">
                VideoLens AI
              </h1>
            </div>
          </div>

          {/* Integrated Segmented Control Navigation */}
          <nav className="flex items-center gap-1 rounded-xl bg-[var(--color-paper-2)] p-1 border border-[var(--color-rule-strong)]" aria-label="Main Navigation">
            {NAV_TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setActiveTab(id)}
                className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-all duration-180 ${
                  activeTab === id
                    ? "bg-[var(--color-accent)] text-[var(--color-accent-ink)] shadow-md"
                    : "text-[var(--color-muted)] hover:text-[var(--color-text-strong)] hover:bg-[var(--color-paper-3)]"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                <span className="hidden xs:inline sm:inline">{label}</span>
              </button>
            ))}
          </nav>
        </header>

        {/* Scrollable Center Content Workspace */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 md:p-8">
          {activeTab === "analyze" && (
            <div className="flex flex-col gap-5 lg:h-full lg:min-h-0">
              <div className="min-w-0 lg:shrink-0">
                <h2 className="text-xl font-bold text-[var(--color-text-strong)] sm:text-2xl">
                  Video & Audio Analysis
                </h2>
                <p className="mt-1 text-xs text-[var(--color-muted)] sm:text-sm">
                  Upload media or paste a public link to get transcripts, summaries, and structured notes.
                </p>
              </div>

              {status === "idle" && <UploadForm onSubmit={submit} />}

              {status !== "idle" && (
                <div
                  className={`lg:shrink-0 ${
                    status === "complete" ? "" : "rounded-xl border border-[var(--color-rule)] bg-[var(--color-paper-2)] p-4 sm:p-6"
                  }`}
                >
                  <RunStatusView status={status} stage={stage} sourceKind={sourceKind} error={error} />
                </div>
              )}

              {error && status !== "failed" && (
                <div
                  role="alert"
                  className="rounded-[var(--radius-md)] border border-[var(--color-danger)] bg-[var(--color-danger-soft)] p-3.5 text-xs leading-5 text-[var(--color-danger)] sm:text-sm lg:shrink-0"
                >
                  {error}
                </div>
              )}

              {status === "complete" && result && (
                <div className="lg:grid lg:min-h-0 lg:flex-1 lg:grid-cols-[3fr_7fr] lg:items-stretch lg:gap-6">
                  {/* Desktop-only sidebar: source card + "analyze another" live here instead of inline with the tabs */}
                  <div className="hidden lg:flex lg:flex-col lg:gap-4 lg:overflow-y-auto">
                    {sourceMetadata && <SourceCard metadata={sourceMetadata} />}
                    <button
                      type="button"
                      onClick={reset}
                      className="text-link self-start text-xs font-medium"
                    >
                      Analyze another file
                    </button>
                  </div>
                  <ResultsView result={result} sourceMetadata={sourceMetadata} />
                </div>
              )}

              {(status === "complete" || status === "failed" || error) && (
                <button
                  type="button"
                  onClick={reset}
                  className={`text-link self-start text-xs font-medium sm:text-sm ${
                    status === "complete" ? "lg:hidden" : ""
                  }`}
                >
                  Analyze another file
                </button>
              )}
            </div>
          )}

          {activeTab === "theme" && (
            <div className="flex flex-col gap-4">
              <div className="min-w-0">
                <h2 className="text-xl font-bold text-[var(--color-text-strong)] sm:text-2xl">
                  Background Themes
                </h2>
              </div>
              <BackgroundPickerPanel />
            </div>
          )}

          {activeTab === "history" && (
            <div className="flex flex-col gap-4 max-w-2xl">
              <div className="min-w-0">
                <h2 className="text-xl font-bold text-[var(--color-text-strong)] sm:text-2xl">
                  Analysis History
                </h2>
              </div>
              <HistoryPanel onOpenRun={handleOpenRun} />
            </div>
          )}

          {activeTab === "api-key" && (
            <div className="flex flex-col gap-4">
              <div className="min-w-0">
                <h2 className="text-xl font-bold text-[var(--color-text-strong)] sm:text-2xl">
                  Gemini API Key
                </h2>
              </div>
              <ApiKeyPanel />
            </div>
          )}

          {activeTab === "releases" && (
            <div className="flex flex-col gap-4 max-w-2xl">
              <div className="min-w-0">
                <h2 className="text-xl font-bold text-[var(--color-text-strong)] sm:text-2xl">
                  Release Notes
                </h2>
              </div>
              <VersionLogPanel />
            </div>
          )}
        </div>

        {/* Integrated Card Footer */}
        <footer className="flex shrink-0 items-center justify-between border-t border-[var(--color-rule)] px-4 py-2.5 text-xs text-[var(--color-faint)] sm:px-6">
          <span>VideoLens AI</span>
          <nav className="flex gap-4" aria-label="Legal">
            <a href="/privacy" className="hover:text-[var(--color-text)] transition-colors">Privacy</a>
            <a href="/terms" className="hover:text-[var(--color-text)] transition-colors">Terms</a>
          </nav>
        </footer>
      </main>
    </div>
  );
}
