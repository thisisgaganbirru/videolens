/* Hallmark · pre-emit critique: P5 H5 E5 S5 R5 V5 */
/* Hallmark · component: run pipeline · genre: terminal (locked) · theme: Terminal
 * Centred single column, direct children of HomeScreen's `.run-state`:
 * status pill, equal-width step tracks joined by a rule, then either the
 * pending note or the error block. No card, no surface, no shadow.
 */

import type { RunStatus } from "@/domain/entities";

type SourceKind = "file" | "url";

interface PipelineStep {
  /** matches the backend `stage` values exactly */
  stage: string;
  label: string;
}

const DOWNLOAD_STEP: PipelineStep = { stage: "downloading", label: "downloading" };

const SHARED_STEPS: PipelineStep[] = [
  { stage: "normalizing", label: "normalizing" },
  { stage: "uploading_to_gemini", label: "uploading to gemini" },
  { stage: "analyzing", label: "analyzing" },
];

/* What to try next, chosen by *where the run died* rather than by what was
   submitted. The two differ, and the old `sourceKind` version got it wrong in
   the case that matters most: a run that downloaded, normalized and uploaded
   fine before Gemini returned 503 was told to "try a different URL", when a
   different URL would have failed in exactly the same place. Anything at or
   after the Gemini upload is ours, and saying so beats sending someone off to
   re-do work that was already good. */
function recoveryAdvice(stage: string | null | undefined, sourceKind: SourceKind): string {
  if (stage === "uploading_to_gemini" || stage === "analyzing") {
    return "Nothing's wrong with your file — this one's on our side. Try again in a moment.";
  }
  if (stage === "downloading") {
    return "Try a different link, or download the video and upload the file instead.";
  }
  /* `normalizing`, or no stage at all: the media itself is the suspect, and
     the only thing we know about it is which way it arrived. */
  return sourceKind === "url" ? "Try a different link." : "Try a different file.";
}

const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "queued",
  processing: "processing",
  complete: "complete",
  failed: "failed",
};

/* Not a `RunStatus`: the run's status is whatever the server last told us, and
   the point of this state is that we no longer know. It describes the screen —
   nothing here is advancing — which is the one thing that is certainly true. */
const STALLED_LABEL = "stalled";

interface RunStatusViewProps {
  status: RunStatus;
  stage?: string | null;
  sourceKind: SourceKind;
  error?: string | null;
  /** Polling threw, so `useAnalysisRun` cleared its interval and nothing on
   *  this screen will change again. Without this the view keeps pulsing an
   *  `active` step and keeps saying "You can leave this open" — two statements
   *  that are false the moment the interval dies. */
  connectionLost?: boolean;
}

/** `undefined` renders no attribute at all, which is the "upcoming" tone. */
function stepStatus(
  index: number,
  activeIndex: number,
  status: RunStatus,
  connectionLost: boolean
): "done" | "active" | "stalled" | undefined {
  if (status === "complete") return "done";
  if (index < activeIndex) return "done";
  // A failed run marks nothing active — the pill already carries the failure,
  // and an accent-pulsing mark under a red pill would contradict it.
  if (status === "failed") return undefined;
  if (index !== activeIndex) return undefined;
  // The last stage we heard about, held rather than animated: it is where the
  // run got to, not where it is.
  return connectionLost ? "stalled" : "active";
}

export default function RunStatusView({
  status,
  stage,
  sourceKind,
  error,
  connectionLost = false,
}: RunStatusViewProps) {
  const steps = sourceKind === "url" ? [DOWNLOAD_STEP, ...SHARED_STEPS] : SHARED_STEPS;
  const stageIndex = stage ? steps.findIndex((step) => step.stage === stage) : -1;
  const activeIndex = stageIndex >= 0 ? stageIndex : 0;

  const tone = connectionLost
    ? "stalled"
    : status === "failed"
      ? "failed"
      : status === "complete"
        ? undefined
        : "processing";

  /* Deliberately silent while stalled: the caller renders a `role="alert"`
     block for this state, and an assertive alert plus a polite status update
     saying the same thing is one announcement too many. */
  const liveMessage = connectionLost
    ? ""
    : status === "failed"
      ? `Analysis failed${error ? `: ${error}` : "."}`
      : status === "complete"
        ? "Analysis complete."
        : `${STATUS_LABEL[status]} — ${steps[activeIndex].label}`;

  return (
    <>
      {/* The pill is the only thing identifying these states — there is no
          source metadata yet and no results to sit beside. */}
      <span className="status" data-tone={tone}>
        <span className="pip" aria-hidden="true" />
        {connectionLost ? STALLED_LABEL : STATUS_LABEL[status]}
      </span>

      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {liveMessage}
      </p>

      <ol className="steps" aria-label="Media analysis pipeline">
        {steps.map((step, index) => {
          const state = stepStatus(index, activeIndex, status, connectionLost);
          return (
            <li
              key={step.stage}
              className="step"
              data-status={state}
              aria-current={state === "active" ? "step" : undefined}
            >
              <span className="step-mark" aria-hidden="true">
                {state === "done" ? "✓" : ""}
              </span>
              <span>{step.label}</span>
            </li>
          );
        })}
      </ol>

      {status === "failed" ? (
        <div className="error-block">
          <p>
            <strong>Analysis failed.</strong>{" "}
            {error || "The run stopped before it could finish."}
          </p>
          {/* the spec's `.error-block p:last-of-type` reserves space for the
              mockup's retry button; HomeScreen owns the reset link here, so
              the reserved gap is cancelled locally rather than in globals */}
          <p className="mb-0">{recoveryAdvice(stage, sourceKind)}</p>
        </div>
      ) : status === "complete" || connectionLost ? null : (
        /* Suppressed while stalled rather than reworded. "You can leave this
           open" is advice about waiting, and there is nothing left to wait for
           on this screen; the caller's error block below says what happened and
           carries the single recovery control. Two error treatments stacked
           would be the same mistake in a different place. */
        <p className="pending-note">
          Longer files take more time to normalize. You can leave this open.
        </p>
      )}
    </>
  );
}
