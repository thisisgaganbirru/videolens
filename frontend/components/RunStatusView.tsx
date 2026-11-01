/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V5 */
/* Hallmark · component: run progress · genre: editorial · theme: custom (owner handoff)
 * Centred single column, direct children of HomeScreen's `.run-state`: status
 * pill, serif title, one-line lede, the filmstrip (one frame per backend
 * stage, sprocket holes top and bottom — or left and right once it stacks on a
 * phone), the source chip, then either the notice card with its actions
 * (failed, connection lost) with its actions centred under it, or the single
 * "stop watching" link. Drawn on design/shots/Progress*.png; the captions-only
 * state, the "File received" frame and the failed / lost notice follow
 * design/newshots/ (ProgressCaptions, ProgressUploadMobile, ProgressFailed,
 * ProgressLostWeb), which supersede the older shots where they differ.
 */

import { Check, WifiOff, X } from "lucide-react";
import type { RunStatus } from "@/domain/entities";
import { reconnectDelayFor } from "@/application/useAnalysisRun";

type SourceKind = "file" | "url";

interface PipelineStep {
  /** matches the backend `stage` values exactly */
  stage: string;
  label: string;
  /** "The run stopped while …" */
  verb: string;
}

const DOWNLOAD_STEP: PipelineStep = {
  stage: "downloading",
  label: "Downloading",
  verb: "downloading",
};

/* Uploads' first frame (ProgressUploadMobile.png). The bytes have already
   arrived by the time a run exists, so it is done from the first paint; no
   backend stage ever names it. */
const FILE_STEP: PipelineStep = {
  stage: "file_received",
  label: "File received",
  verb: "receiving the file",
};

const SHARED_STEPS: PipelineStep[] = [
  { stage: "normalizing", label: "Normalizing", verb: "normalizing" },
  { stage: "uploading_to_gemini", label: "Uploading", verb: "uploading" },
  { stage: "analyzing", label: "Analyzing", verb: "analyzing" },
];

function stepsFor(sourceKind: SourceKind): PipelineStep[] {
  return [sourceKind === "url" ? DOWNLOAD_STEP : FILE_STEP, ...SHARED_STEPS];
}

/* `analyzing_captions` is the salvage path (backend process_run.py): every
   download route failed, so the backend fetched the caption track and went
   straight to analysis — normalizing and the Gemini upload never run. It has
   no frame of its own; it lands on Analyzing, and `captionsRoute` below
   redraws the frames before it (ProgressCaptions.png). */
const STAGE_ALIASES: Record<string, string> = {
  analyzing_captions: "analyzing",
};

/** Index of the frame for `stage`, or -1 when we cannot honestly place it. */
function frameIndex(steps: PipelineStep[], stage: string | null | undefined): number {
  if (!stage) return -1;
  const key = STAGE_ALIASES[stage] ?? stage;
  return steps.findIndex((step) => step.stage === key);
}

/* What to try next, chosen by *where the run died* rather than by what was
   submitted. The two differ, and the old `sourceKind` version got it wrong in
   the case that matters most: a run that downloaded, normalized and uploaded
   fine before Gemini returned 503 was told to "try a different URL", when a
   different URL would have failed in exactly the same place. Anything at or
   after the Gemini upload is ours, and saying so beats sending someone off to
   re-do work that was already good. */
function recoveryAdvice(stage: string | null | undefined, sourceKind: SourceKind): string {
  const key = stage ? (STAGE_ALIASES[stage] ?? stage) : stage;
  if (key === "uploading_to_gemini" || key === "analyzing") {
    /* ProgressFailed.png's copy. The server's own message ("Your file is
       fine…") follows in the notice below, so this line only says what to do. */
    return `You can try the same ${sourceKind === "url" ? "link" : "file"} again.`;
  }
  if (key === "downloading") {
    return "Try a different link, or download the video and upload the file instead.";
  }
  /* `normalizing`, or no stage at all: the media itself is the suspect, and
     the only thing we know about it is which way it arrived. */
  return sourceKind === "url" ? "Try a different link." : "Try a different file.";
}

type FrameState = "done" | "active" | "waiting" | "failed" | "lost" | "missed" | "skipped";

const FRAME_CAPTION: Record<FrameState, string> = {
  done: "Done",
  active: "In progress",
  waiting: "Waiting",
  failed: "Stopped here",
  lost: "Waiting for connection",
  /* Captions route only: the download failed but the run carried on. */
  missed: "Couldn't download",
  skipped: "Skipped",
};

/** One frame's state. Reused shape of the old `stepStatus`: everything before
 *  the current frame is done, the current one carries the run's condition,
 *  everything after it waits. */
function stepStatus(
  index: number,
  currentIndex: number,
  status: RunStatus,
  connectionLost: boolean
): FrameState {
  if (status === "complete") return "done";
  if (currentIndex < 0) return "waiting";
  if (index < currentIndex) return "done";
  if (index > currentIndex) return "waiting";
  if (status === "failed") return "failed";
  // The last stage we heard about, held rather than animated: it is where the
  // run got to, not where it is.
  return connectionLost ? "lost" : "active";
}

const PILL: Record<"queued" | "processing" | "failed" | "lost" | "complete", string> = {
  queued: "Queued",
  processing: "Processing",
  failed: "Failed",
  lost: "Connection lost",
  complete: "Complete",
};

interface RunStatusViewProps {
  status: RunStatus;
  stage?: string | null;
  sourceKind: SourceKind;
  error?: string | null;
  /** Polling threw. `useAnalysisRun` is now counting down to its next
   *  reconnect attempt; nothing on this screen advances until one succeeds. */
  connectionLost?: boolean;
  /** The link or file name, for the source chip. Absent for a run reopened
   *  from History before its metadata has arrived. */
  sourceLabel?: string | null;
  /** Whole seconds until the next automatic reconnect, ticking. */
  retryInSeconds?: number | null;
  /** A reconnect attempt is on the wire right now. */
  retrying?: boolean;
  /** Failed reconnect attempts so far (1-based). Drives the one polite
   *  announcement per attempt — never the per-second countdown. */
  reconnectAttempt?: number;
  /** Resubmitting the failed source is in flight. */
  retryBusy?: boolean;
  onReset?: () => void;
  /** Failed runs only, and only when there is a source to resubmit. */
  onRetry?: () => void;
  /** Connection lost only: skip the rest of the countdown. */
  onRetryNow?: () => void;
}

export default function RunStatusView({
  status,
  stage,
  sourceKind,
  error,
  connectionLost = false,
  sourceLabel,
  retryInSeconds = null,
  retrying = false,
  reconnectAttempt = 0,
  retryBusy = false,
  onReset,
  onRetry,
  onRetryNow,
}: RunStatusViewProps) {
  const steps = stepsFor(sourceKind);
  const currentIndex = frameIndex(steps, stage);
  const current = currentIndex >= 0 ? steps[currentIndex] : null;
  /* The download failed and the run is reading captions instead. Only a link
     run can get here; the sourceKind check keeps a reopened run whose kind we
     could not tell from drawing "Couldn't download" over a file. */
  const captionsRoute = stage === "analyzing_captions" && sourceKind === "url";

  function frameState(step: PipelineStep, index: number): FrameState {
    if (step === FILE_STEP) return "done";
    if (captionsRoute && status !== "complete") {
      if (step === DOWNLOAD_STEP) return "missed";
      if (index < currentIndex) return "skipped";
    }
    return stepStatus(index, currentIndex, status, connectionLost);
  }

  const mode = connectionLost
    ? "lost"
    : status === "failed"
      ? "failed"
      : status === "complete"
        ? "complete"
        : status === "queued"
          ? "queued"
          : "processing";

  const title =
    mode === "failed"
      ? "That didn't work"
      : mode === "lost"
        ? "Connection lost"
        : captionsRoute
          ? "Reading the captions"
          : "Reading your video";

  const lede =
    mode === "failed"
      ? `${current ? `The run stopped while ${current.verb}. ` : ""}${recoveryAdvice(stage, sourceKind)}`
      : mode === "lost"
        ? "Check your network. The page reconnects on its own and picks up where it left off."
        : mode === "queued"
          ? "Your run is in line and starts in a moment. You can leave this open."
          : captionsRoute
            ? "We couldn't download the video, so we are using its captions only. Results may have less detail."
            : "Longer files take more time to normalize. You can leave this open.";

  /* One sentence per state change. While the connection is lost it changes
     once per failed attempt (`reconnectAttempt`), quoting that attempt's full
     wait — the visible countdown below ticks every second and is deliberately
     outside any live region. */
  const liveMessage =
    mode === "lost"
      ? retrying
        ? "Trying to reconnect."
        : `Connection lost. Trying again in ${reconnectDelayFor(reconnectAttempt)} seconds.`
      : mode === "failed"
        ? `Analysis failed${error ? `: ${error}` : "."}`
        : mode === "complete"
          ? "Analysis complete."
          : `${PILL[mode]}${captionsRoute ? " — Analyzing captions" : current ? ` — ${current.label}` : ""}`;

  const countdown = retrying
    ? "Trying to reconnect…"
    : retryInSeconds !== null
      ? `Trying again in ${retryInSeconds} ${retryInSeconds === 1 ? "second" : "seconds"}.`
      : "";

  return (
    <>
      <span className="status" data-tone={mode}>
        <span className="pip" aria-hidden="true" />
        {PILL[mode]}
      </span>

      <h1 className="run-title">{title}</h1>
      <p className="run-lede">{lede}</p>

      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {liveMessage}
      </p>

      <div className="filmstrip" data-mode={mode}>
        <ol className="filmstrip-frames" aria-label="Analysis steps">
          {steps.map((step, index) => {
            const state = frameState(step, index);
            return (
              <li
                key={step.stage}
                className="frame"
                data-state={state}
                aria-current={state === "active" ? "step" : undefined}
              >
                {state === "active" ? <span className="frame-scan" aria-hidden="true" /> : null}
                <span className="frame-num" aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="frame-text">
                  <span className="frame-label">{step.label}</span>
                  <span className="frame-caption">{FRAME_CAPTION[state]}</span>
                </span>
                <span className="frame-icon" aria-hidden="true">
                  {state === "done" ? (
                    <Check size={18} strokeWidth={2.5} />
                  ) : state === "failed" || state === "missed" ? (
                    <X size={18} strokeWidth={2.5} />
                  ) : state === "lost" ? (
                    <WifiOff size={18} strokeWidth={2} />
                  ) : null}
                </span>
              </li>
            );
          })}
        </ol>
      </div>

      {/* No chip once the run has stopped or gone quiet: ProgressFailed and
          ProgressLostWeb put the message card straight under the strip. */}
      {sourceLabel && mode !== "failed" && mode !== "lost" ? (
        <p className="source-chip">
          <span className="source-chip__kind">{sourceKind === "url" ? "Link" : "File"}</span>
          <span className="source-chip__name">{sourceLabel}</span>
        </p>
      ) : null}

      {mode === "failed" || mode === "lost" ? (
        /* ProgressFailed.png / ProgressLostWeb.png: the message in its own
           card, the actions centred under it (full width on a phone). */
        <>
          <p className="run-notice" data-tone={mode}>
            {mode === "failed"
              ? error || "The run stopped before it could finish."
              : `We can't reach the server right now. ${countdown}`}
          </p>
          <div className="run-actions">
            {mode === "failed" && onRetry ? (
              <button
                type="button"
                className="btn btn-ink"
                onClick={onRetry}
                disabled={retryBusy}
                aria-busy={retryBusy || undefined}
              >
                {retryBusy ? "Starting…" : "Try again"}
              </button>
            ) : null}
            {mode === "lost" && onRetryNow ? (
              <button
                type="button"
                className="btn btn-ink"
                onClick={onRetryNow}
                disabled={retrying}
                aria-busy={retrying || undefined}
              >
                {retrying ? "Trying…" : "Retry now"}
              </button>
            ) : null}
            {onReset ? (
              /* Lost: the run is still going on the server, so this only
                 stops this page watching it (ProgressLostWeb's own label).
                 Failed: there is nothing left to watch. */
              <button type="button" className="btn btn-secondary" onClick={onReset}>
                {mode === "lost" ? "Stop watching" : "Analyze another file"}
              </button>
            ) : null}
          </div>
        </>
      ) : mode !== "complete" && onReset ? (
        /* "Cancel" on the boards, but reset only stops this page watching —
           the server finishes the run regardless, and it still lands in
           History. The label says what the button actually does. */
        <button type="button" className="reset-link" onClick={onReset}>
          Stop watching and analyze another file
        </button>
      ) : null}
    </>
  );
}
