/* Hallmark · pre-emit critique: P5 H5 E5 S5 R5 V4 */
/* Hallmark · component: processing pipeline · genre: atmospheric · theme: existing slate/indigo */

import type { RunStatus } from "@/lib/types";

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
    complete: "border-slate-400 bg-slate-950 text-slate-300",
    active: "border-white bg-slate-950 text-white",
    failed: "border-red-400 bg-red-950 text-red-200",
    upcoming: "border-slate-700 bg-slate-950 text-slate-500",
  }[state];

  return (
    <span
      className={`relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border text-sm font-semibold tabular-nums ${markerClass}`}
      aria-hidden="true"
    >
      {state === "complete" ? <span>&#10003;</span> : state === "failed" ? "!" : number}
      {state === "active" && (
        <span className="absolute -inset-1 animate-spin rounded-full border border-transparent border-t-white motion-reduce:animate-none" />
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
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-slate-500 bg-slate-900 text-sm font-semibold text-slate-300"
            aria-hidden="true"
          >
            <span>&#10003;</span>
          </span>
          <p className="text-sm font-medium text-slate-300">Analysis complete</p>
        </div>
      </section>
    );
  }

  return (
    <section
      className="py-2"
      aria-live="polite"
      aria-busy={status === "queued" || status === "processing"}
    >
      <div className="mb-7 border-b border-slate-800 pb-5">
        <h2 className="text-lg font-semibold text-slate-100">{statusCopy.title}</h2>
        <p className="mt-1 text-sm leading-6 text-slate-400">{statusCopy.detail}</p>
      </div>

      <ol aria-label="Media analysis pipeline">
        {steps.map((step, index) => {
          const stepState = getStepState(index, activeIndex, status);
          const isLast = index === steps.length - 1;

          return (
            <li
              key={step.stage}
              className={`relative flex gap-4 ${isLast ? "" : "pb-8"}`}
              aria-current={stepState === "active" ? "step" : undefined}
            >
              {!isLast && (
                <span
                  className={`absolute bottom-0 left-[15px] top-8 border-l ${
                    stepState === "complete"
                      ? "border-solid border-slate-500"
                      : "border-dotted border-slate-700"
                  }`}
                  aria-hidden="true"
                />
              )}
              <StepMarker number={index + 1} state={stepState} />
              <div className="min-w-0 pt-0.5">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <h3
                    className={`text-base font-semibold ${
                      stepState === "upcoming" ? "text-slate-500" : "text-slate-100"
                    }`}
                  >
                    {step.title}
                  </h3>
                  <span
                    className={`text-sm font-medium ${
                      stepState === "complete"
                        ? "text-slate-300"
                        : stepState === "active"
                          ? "text-white"
                          : stepState === "failed"
                            ? "text-red-300"
                            : "text-slate-600"
                    }`}
                  >
                    {stepState === "complete"
                      ? "Completed"
                      : stepState === "active"
                        ? "Running"
                        : stepState === "failed"
                          ? "Failed"
                          : "Waiting"}
                  </span>
                </div>
                {stepState === "failed" && error ? (
                  <p className="mt-1 max-w-prose text-sm leading-6 text-red-300">{error}</p>
                ) : (
                  <p
                    className={`mt-1 max-w-prose text-sm leading-6 ${
                      stepState === "upcoming" ? "text-slate-600" : "text-slate-400"
                    }`}
                  >
                    {step.description}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
