/* Hallmark · lifecycle preview: queued · stages · error · success */

import RunStatusView from "./RunStatusView";
import type { RunStatus } from "@/lib/types";

const PREVIEW_STATES: Array<{
  label: string;
  status: RunStatus;
  stage: string | null;
  sourceKind: "file" | "url";
}> = [
  { label: "Queued", status: "queued", stage: null, sourceKind: "url" },
  { label: "Downloading", status: "processing", stage: "downloading", sourceKind: "url" },
  { label: "Preparing", status: "processing", stage: "normalizing", sourceKind: "url" },
  {
    label: "Uploading",
    status: "processing",
    stage: "uploading_to_gemini",
    sourceKind: "url",
  },
  { label: "Analyzing", status: "processing", stage: "analyzing", sourceKind: "url" },
  { label: "Failed", status: "failed", stage: "analyzing", sourceKind: "url" },
  { label: "URL complete", status: "complete", stage: "analyzing", sourceKind: "url" },
  { label: "File complete", status: "complete", stage: "analyzing", sourceKind: "file" },
];

export default function RunStatusViewPreview() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-10 px-4 py-12">
      {PREVIEW_STATES.map((preview) => (
        <section key={preview.label} className="flex flex-col gap-3">
          <p className="text-sm font-semibold text-slate-400">{preview.label}</p>
          <RunStatusView
            status={preview.status}
            stage={preview.stage}
            sourceKind={preview.sourceKind}
          />
        </section>
      ))}
    </main>
  );
}
