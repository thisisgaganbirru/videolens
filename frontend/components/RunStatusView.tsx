/* Hallmark · pre-emit critique: P5 H5 E5 S5 R5 V4 */
/* Hallmark · component: processing pipeline · genre: atmospheric · theme: existing slate/indigo */

import type { RunStatus } from "@/domain/entities";

type SourceKind = "file" | "url";
type StepState = "complete" | "active" | "upcoming" | "failed";

interface PipelineStep {
  stage: string;
  title: string;
  description: string;
}

const DOWNLOAD_STEP: PipelineStep = {
  stage: "downloading",
  title: "Download media",
  description: "Fetch the public media from its source.",
};

const SHARED_STEPS: PipelineStep[] = [
  {
    stage: "normalizing",
    title: "Prepare media",
    description: "Check duration and convert the file for analysis.",
  },
  {
    stage: "uploading_to_gemini",
    title: "Send to Gemini",
    description: "Transfer the prepared media for processing.",
  },
  {
    stage: "analyzing",
    title: "Analyze content",
    description: "Read speech, visuals, and on-screen text.",
  },
];

const STATUS_COPY: Record<RunStatus, { title: string; detail: string }> = {
  queued: {
    title: "Analysis queued",
    detail: "The pipeline will begin shortly.",
  },
  processing: {
    title: "Analysis in progress",
    detail: "Keep this page open while the media is processed.",
  },
  complete: {
    title: "Analysis complete",
    detail: "Your transcript and notes are ready.",
  },
  failed: {
    title: "Analysis stopped",
    detail: "Review the error below, then try the media again.",
  },
};

interface RunStatusViewProps {
  status: RunStatus;
  stage?: string | null;
  sourceKind: SourceKind;
  error?: string | null;
}

function getStepState(
  index: number,
  activeIndex: number,
  status: RunStatus
): StepState {
  if (status === "complete") return "complete";
  if (status === "failed") {
    if (index < activeIndex) return "complete";
    return index === activeIndex ? "failed" : "upcoming";
  }
  if (index < activeIndex) return "complete";
  return index === activeIndex ? "active" : "upcoming";
}

function StepMarker({ number, state }: { number: number; state: StepState }) {
  const markerClass = {
    complete: "border-[var(--color-success)] bg-[var(--color-paper)] text-[var(--color-success)]",
    active: "border-[var(--color-text-strong)] bg-[var(--color-paper)] text-[var(--color-text-strong)]",
    failed: "border-[var(--color-danger)] bg-[var(--color-danger-soft)] text-[var(--color-danger)]",
    upcoming: "border-[var(--color-rule-strong)] bg-[var(--color-paper)] text-[var(--color-faint)]",
  }[state];

  return (
    <span
      className={`relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border text-sm font-semibold tabular-nums ${markerClass}`}
      aria-hidden="true"
    >
      {state === "complete" ? <span>&#10003;</span> : state === "failed" ? "!" : number}
      {state === "active" && (
        <span className="absolute -inset-1 animate-spin rounded-full border border-transparent border-t-[var(--color-focus)] motion-reduce:animate-none" />
      )}
    </span>
  );
}

export default function RunStatusView({ status, stage, sourceKind, error }: RunStatusViewProps) {
  const steps = sourceKind === "url" ? [DOWNLOAD_STEP, ...SHARED_STEPS] : SHARED_STEPS;
  const stageIndex = stage ? steps.findIndex((step) => step.stage === stage) : -1;
  const activeIndex = stageIndex >= 0 ? stageIndex : 0;
  const statusCopy = STATUS_COPY[status];

  if (status === "complete") {
    return (
      <section className="py-2" aria-live="polite">
        <div className="flex items-center gap-3">
          <span
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-[var(--color-success)] bg-[var(--color-paper)] text-sm font-semibold text-[var(--color-success)]"
            aria-hidden="true"
          >
            <span>&#10003;</span>
          </span>
          <p className="text-sm font-medium text-[var(--color-text)]">Analysis complete</p>
        </div>
      </section>
    );
  }

  const activeStep = steps[activeIndex];
  const activeState = getStepState(activeIndex, activeIndex, status);

  return (
    <section
      className="py-2"
      aria-live="polite"
      aria-busy={status === "queued" || status === "processing"}
    >
      <div className="mb-5 border-b border-[var(--color-rule)] pb-4">
        <h2 className="text-xl font-semibold text-[var(--color-text-strong)]">{statusCopy.title}</h2>
        <p className="mt-1 text-base leading-6 text-[var(--color-muted)]">{statusCopy.detail}</p>
      </div>

      <ol aria-label="Media analysis pipeline" className="flex items-start">
        {steps.map((step, index) => {
          const stepState = getStepState(index, activeIndex, status);
          const isLast = index === steps.length - 1;

          return (
            <li
              key={step.stage}
              className={`flex items-center ${isLast ? "" : "flex-1"}`}
              aria-current={stepState === "active" ? "step" : undefined}
            >
              <div className="flex flex-col items-center gap-1.5">
                <StepMarker number={index + 1} state={stepState} />
                <span
                  className={`hidden text-center text-[11px] font-medium leading-tight sm:block ${
                    stepState === "upcoming" ? "text-[var(--color-faint)]" : "text-[var(--color-text-strong)]"
                  }`}
                >
                  {step.title}
                </span>
              </div>
              {!isLast && (
                <span
                  className={`mx-2 h-px flex-1 self-start mt-4 ${
                    stepState === "complete"
                      ? "border-t border-solid border-[var(--color-success)]"
                      : "border-t border-dotted border-[var(--color-rule-strong)]"
                  }`}
                  aria-hidden="true"
                />
              )}
            </li>
          );
        })}
      </ol>

      <div className="mt-6 rounded-[var(--radius-md)] border border-[var(--color-rule)] bg-[var(--color-paper-2)] p-4">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="text-base font-semibold text-[var(--color-text-strong)]">{activeStep.title}</h3>
          <span
            className={`text-sm font-medium ${
              activeState === "active"
                ? "text-[var(--color-text-strong)]"
                : activeState === "failed"
                  ? "text-[var(--color-danger)]"
                  : "text-[var(--color-faint)]"
            }`}
          >
            {activeState === "active" ? "Running" : activeState === "failed" ? "Failed" : "Waiting"}
          </span>
        </div>
        {activeState === "failed" && error ? (
          <p className="mt-1 max-w-prose text-sm leading-6 text-[var(--color-danger)]">{error}</p>
        ) : (
          <p className="mt-1 max-w-prose text-sm leading-6 text-[var(--color-muted)]">{activeStep.description}</p>
        )}
      </div>
    </section>
  );
}
