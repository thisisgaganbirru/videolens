import type { JobStatus } from "@/lib/types";

const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued...",
  processing: "Analyzing video with Gemini...",
  complete: "Complete",
  failed: "Failed",
};

export default function JobStatusView({ status }: { status: JobStatus }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900 p-6">
      {(status === "queued" || status === "processing") && (
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-600 border-t-indigo-400" />
      )}
      <span className="text-sm font-medium">{STATUS_LABEL[status]}</span>
    </div>
  );
}
