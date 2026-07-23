import type { JobStatus } from "@/lib/types";

const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued...",
  processing: "Processing...",
  complete: "Complete",
  failed: "Failed",
};

const STAGE_LABEL: Record<string, string> = {
  normalizing: "Preparing video...",
  uploading_to_gemini: "Uploading to Gemini...",
  analyzing: "Analyzing speech and visuals...",
};

interface JobStatusViewProps {
  status: JobStatus;
  stage?: string | null;
}

export default function JobStatusView({ status, stage }: JobStatusViewProps) {
  const label = (stage && STAGE_LABEL[stage]) || STATUS_LABEL[status];

  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900 p-6">
      {(status === "queued" || status === "processing") && (
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-600 border-t-indigo-400" />
      )}
      <span className="text-sm font-medium">{label}</span>
    </div>
  );
}
