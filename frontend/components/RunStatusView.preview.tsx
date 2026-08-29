/* Hallmark · lifecycle preview: queued · stages · failed · complete
 * Dev-only harness. Mirrors HomeScreen's real wrapper (`.run-state`) so the
 * centred single-column pipeline renders exactly as it ships. Not routed —
 * mount it temporarily under app/ to eyeball changes, then remove.
 */

import RunStatusView from "./RunStatusView";
import type { RunStatus } from "@/domain/entities";

const PREVIEW_STATES: Array<{
  label: string;
  status: RunStatus;
  stage: string | null;
  sourceKind: "file" | "url";
  error?: string;
  connectionLost?: boolean;
}> = [
  { label: "Queued", status: "queued", stage: null, sourceKind: "url" },
  { label: "Downloading", status: "processing", stage: "downloading", sourceKind: "url" },
  { label: "Normalizing", status: "processing", stage: "normalizing", sourceKind: "url" },
  {
    label: "Uploading to Gemini",
    status: "processing",
    stage: "uploading_to_gemini",
    sourceKind: "url",
  },
  { label: "Analyzing", status: "processing", stage: "analyzing", sourceKind: "url" },
  { label: "File run — normalizing (no download step)", status: "processing", stage: "normalizing", sourceKind: "file" },
  {
    label: "Failed",
    status: "failed",
    stage: "downloading",
    sourceKind: "url",
    error: "The source video couldn't be downloaded — it may be private, age-restricted, or region-locked.",
  },
  /* The stalled state ships without the error block that accompanies it in
     HomeScreen — this harness is for the pipeline itself, and the point to
     eyeball here is that nothing pulses and nothing claims to be waiting. */
  {
    label: "Connection lost mid-run (polling died)",
    status: "processing",
    stage: "uploading_to_gemini",
    sourceKind: "url",
    error: "Can't reach the server. It may be offline, or your connection dropped.",
    connectionLost: true,
  },
  { label: "URL complete", status: "complete", stage: "analyzing", sourceKind: "url" },
  { label: "File complete", status: "complete", stage: "analyzing", sourceKind: "file" },
];

export default function RunStatusViewPreview() {
  return (
    <main className="mx-auto flex w-full max-w-[48rem] flex-col gap-[var(--space-xl)] px-[var(--space-sm)] py-[var(--space-xl)]">
      {PREVIEW_STATES.map((preview) => (
        <section key={preview.label} className="flex flex-col gap-[var(--space-sm)]">
          <p className="card-label">{preview.label}</p>
          <div className="run-state">
            <RunStatusView
              status={preview.status}
              stage={preview.stage}
              sourceKind={preview.sourceKind}
              error={preview.error}
              connectionLost={preview.connectionLost}
            />
          </div>
        </section>
      ))}
    </main>
  );
}
