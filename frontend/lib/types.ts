export type JobStatus = "queued" | "processing" | "complete" | "failed";

export interface VideoAnalysis {
  title: string;
  summary: string;
  transcript: string;
  screen_text: string;
  markdown: string;
}

export interface JobCreateResponse {
  job_id: string;
  status: JobStatus;
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  result: VideoAnalysis | null;
  error: string | null;
}
