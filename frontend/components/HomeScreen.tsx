"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import AppNav from "@/components/AppNav";
import UploadForm from "@/components/UploadForm";
import RunStatusView from "@/components/RunStatusView";
import ResultsView, { SourceCard } from "@/components/ResultsView";
import ApiKeyPanel from "@/components/panels/ApiKeyPanel";
import HistoryPanel from "@/components/panels/HistoryPanel";
import VersionLogPanel from "@/components/panels/VersionLogPanel";
import { useAnalysisRun } from "@/application/useAnalysisRun";
import { goToMainTab, useMainTab, type MainTab } from "@/application/useMainTab";

/**
 * The app shell for one tab.
 *
 * Takes the tab as a prop rather than reading the URL itself, so it can be
 * rendered both as the resolved route and as `app/page.tsx`'s Suspense
 * fallback — the fallback is what gets baked into the prerendered HTML, and it
 * has to be a real Analyze view, not a placeholder.
 */
export default function HomeScreen({ activeTab }: { activeTab: MainTab }) {
  const [sourceOpen, setSourceOpen] = useState(false);
  const {
    status,
    stage,
    sourceKind,
    result,
    sourceMetadata,
    error,
    errorKind,
    submitting,
    submit,
    reset,
    openRun,
  } = useAnalysisRun();

  /* An error while the pipeline is on screen can only come from the poll's
     catch — `submit` now stays on idle until the server answers, and `openRun`
     returns to idle on failure. So this is precisely "the interval is dead":
     nothing above will ever update again. */
  const connectionLost = Boolean(error) && (status === "queued" || status === "processing");

  const handleOpenRun = (runId: string) => {
    /* Pushes a history entry, so back from a run lands on the list it was
       opened from rather than dropping out of the app. */
    goToMainTab("analyze");
    void openRun(runId);
  };

  /* "fixed" is the one-viewport frame where only the results pane scrolls.
     It applies on mobile whenever there is a results pane to bound; every
     other state lets the page flow and scroll normally. From 32rem up the
     stylesheet puts every view back on the fixed frame. */
  const frame = activeTab === "analyze" && status === "complete" && !sourceOpen ? "fixed" : "flow";

  return (
    <div className="shell" data-view={activeTab} data-frame={frame}>
      <AppNav activeTab={activeTab} onSelectTab={goToMainTab} />

      {activeTab === "analyze" && (
        <section data-view="analyze" aria-label="Analyze">
          {status === "idle" && (
            <div className="home-center">
              <div className="intake">
                <p className="card-label">new analysis</p>
                <UploadForm onSubmit={submit} submitting={submitting} />
                {/* Back at idle with an error means the submit was rejected, or
                    a history row would not open. Either way the control that
                    failed is still on screen — and, since `submit` no longer
                    unmounts this branch while the request is in flight, so is
                    whatever the user typed. Pressing the same button again is
                    the whole recovery, so this is a form-level line in
                    UploadForm's own error slot, not the centred `.error-block`,
                    which is drawn for a full-view failure with an action of its
                    own. */}
                {error && (
                  <p
                    role="alert"
                    data-error-kind={errorKind ?? undefined}
                    className="error-note mt-[var(--space-xs)]"
                  >
                    {error}
                  </p>
                )}
              </div>
            </div>
          )}

          {(status === "queued" || status === "processing" || status === "failed") && (
            <div className="home-center">
              <div className="run-state">
                <RunStatusView
                  status={status}
                  stage={stage}
                  sourceKind={sourceKind}
                  error={error}
                  connectionLost={connectionLost}
                />
                {connectionLost ? (
                  /* Polling threw, so `useAnalysisRun` cleared its interval: the
                     pipeline above is now frozen and nothing on this screen will
                     ever update again. That is a genuine full stop, which is what
                     `.error-block` was drawn for — lead, explanation, and an
                     action inside the block, so the spec's reserved
                     `p:last-of-type` margin is the gap above the button rather
                     than dead space. The button replaces the `.reset-link` here
                     instead of joining it: two ways to start over is one too
                     many, and `.btn` is the one that gets a 44px target on
                     touch. The same flag stops `RunStatusView` pulsing and
                     removes its "you can leave this open" note, so this block is
                     the only thing on screen describing the failure. */
                  <div role="alert" data-error-kind={errorKind ?? undefined} className="error-block">
                    {/* The lead says what happened to the *run*; the gateway's
                        message already says why the request failed, so
                        repeating "lost contact" here would be the same
                        sentence twice. */}
                    <p>
                      <strong>This run stopped updating.</strong> {error}
                    </p>
                    <p>
                      It may still finish on the server — reopen it from History in a
                      moment, or start over.
                    </p>
                    <button type="button" className="btn btn-secondary" onClick={reset}>
                      start over
                    </button>
                  </div>
                ) : (
                  <button type="button" className="reset-link" onClick={reset}>
                    analyze another file
                  </button>
                )}
              </div>
            </div>
          )}

          {status === "complete" && result && (
            <div className="workspace">
              {/* Two ruled columns, no card on either side: the single vertical
                  hairline on .right-col is the whole separation, and only the
                  results pane carries the paper-2 tint. */}
              <div className="left-col" data-collapsed={sourceOpen ? "false" : "true"}>
                <button
                  type="button"
                  className="col-label"
                  onClick={() => setSourceOpen((open) => !open)}
                  aria-expanded={sourceOpen}
                  aria-controls="source-panel"
                >
                  Source
                  <ChevronDown className="col-chevron" aria-hidden="true" />
                </button>
                <div className="source-frame" id="source-panel">
                  <div className="source-body">
                    {sourceMetadata ? (
                      <SourceCard metadata={sourceMetadata} />
                    ) : (
                      <p className="pending-note">No source metadata for this run.</p>
                    )}
                  </div>
                  <button type="button" className="reset-link" onClick={reset}>
                    analyze another file
                  </button>
                </div>
              </div>

              <div className="right-col">
                <p className="col-label">Results</p>
                <div className="results">
                  <ResultsView result={result} sourceMetadata={sourceMetadata} />
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {/* `.tab-view` carries the top margin that lines these labels up with
          `.workspace`'s. It is a class rather than a list of view names in the
          selector so a fifth tab inherits the alignment instead of silently
          missing it — and so `legal`/`offline`, which are sections too but not
          tabs, stay out of it. */}
      {activeTab === "history" && (
        <section className="tab-view" data-view="history" aria-label="History">
          <p className="col-label">History</p>
          <div className="surface">
            <div className="pane">
              <HistoryPanel onOpenRun={handleOpenRun} />
            </div>
          </div>
        </section>
      )}

      {activeTab === "api-key" && (
        <section className="tab-view" data-view="api-key" aria-label="API key">
          <p className="col-label">API key</p>
          <div className="surface">
            <div className="pane">
              <ApiKeyPanel />
            </div>
          </div>
        </section>
      )}

      {activeTab === "releases" && (
        <section className="tab-view" data-view="releases" aria-label="Releases">
          <p className="col-label">Releases</p>
          <div className="surface">
            <div className="pane">
              <VersionLogPanel />
            </div>
          </div>
        </section>
      )}

      <div className="page-end">
        <footer className="foot">
          <span>VideoLens AI</span>
          <nav className="foot-legal" aria-label="Legal">
            <a href="/privacy">Privacy</a>
            <a href="/terms">Terms</a>
          </nav>
        </footer>
      </div>
    </div>
  );
}

/**
 * The same shell, told which tab it is by the URL.
 *
 * Split out so the `useSearchParams` call sits in exactly one component: it is
 * what suspends during prerender, and putting it in `HomeScreen` itself would
 * make the Suspense fallback suspend too.
 */
export function RoutedHomeScreen() {
  const activeTab = useMainTab();
  return <HomeScreen activeTab={activeTab} />;
}
