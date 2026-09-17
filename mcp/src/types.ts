/* Wire shapes, mirroring `backend/app/interface/api/schemas.py`. Kept as
   plain interfaces (no runtime validation): the backend is ours, and the
   agent receives the JSON verbatim anyway. */

export type RunStatus = "queued" | "processing" | "complete" | "failed";

export interface TranscriptSegment {
  start_seconds: number;
  end_seconds: number;
  text: string;
  speaker?: string | null;
}

export interface ScreenTextSegment {
  start_seconds: number;
  end_seconds: number;
  text: string;
}

export interface VideoAnalysis {
  title: string;
  summary: string;
  transcript: string;
  transcript_segments?: TranscriptSegment[];
  screen_text: string;
  screen_text_segments?: ScreenTextSegment[];
  markdown: string;
}

export interface SourceMetadata {
  platform: string;
  source_url: string;
  title?: string | null;
  uploader?: string | null;
  uploader_url?: string | null;
  description?: string | null;
  upload_date?: string | null;
  like_count?: number | null;
  view_count?: number | null;
  comment_count?: number | null;
}

export interface RunCreateResponse {
  run_id: string;
  status: RunStatus;
}

export interface RunStatusResponse {
  run_id: string;
  status: RunStatus;
  stage: string | null;
  result: VideoAnalysis | null;
  source_metadata?: SourceMetadata | null;
  completeness?: "full" | "captions_only";
  error: string | null;
}

export interface RunSummary {
  run_id: string;
  status: RunStatus;
  title: string | null;
  created_at: string;
}

export interface RunListResponse {
  runs: RunSummary[];
}

export interface LibraryEntry {
  run_id: string;
  status: RunStatus;
  title: string | null;
  summary: string | null;
  platform: string | null;
  source_url: string | null;
  duration_seconds: number | null;
  completeness?: "full" | "captions_only";
  created_at: string;
}

export interface LibraryResponse {
  runs: LibraryEntry[];
  query: string;
  limit: number;
  offset: number;
}

export interface LibraryQuery {
  query?: string;
  platform?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export interface AccountResponse {
  subject: string;
  method: string;
  email: string | null;
  account_id: string | null;
  workspace: { workspace_id: string; name: string; plan: string; seats: number; has_subscription: boolean } | null;
  usage: {
    plan: string;
    minutes_included: number;
    minutes_used: number;
    minutes_remaining: number;
    period_start: string;
    period_end: string;
    max_duration_seconds: number;
    overage_usd_per_minute: number | null;
  };
  billing_enabled: boolean;
  accounts_enabled: boolean;
  api_access: boolean;
  library: boolean;
}
