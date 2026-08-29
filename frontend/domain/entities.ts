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

export interface RunCreateResponse {
  run_id: string;
  status: RunStatus;
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

/** What the analysis was actually able to look at.
 *
 *  `captions_only` is the salvage path: every download route for a URL failed
 *  (a platform serving `HTTP 403` on the media while serving subtitles fine is
 *  the reproducible case), so the backend analyzed the subtitle track instead
 *  of failing the run. There were no frames — `screen_text` is empty because
 *  nothing was ever looked at, not because nothing was there.
 *
 *  A closed union, matching `RunStatus` above rather than the deliberately
 *  widened `CapabilityState` below. The widening there exists because that
 *  endpoint renders every row it receives, so an unrecognised one must still
 *  appear. This field is the opposite: the UI says nothing unless the value is
 *  literally `captions_only`, so an unknown future value already falls to the
 *  quiet, safe default with no type-level licence needed. */
export type AnalysisCompleteness = "full" | "captions_only";

export interface RunStatusResponse {
  run_id: string;
  status: RunStatus;
  stage: string | null;
  result: VideoAnalysis | null;
  source_metadata?: SourceMetadata | null;
  /** Optional on the wire: a backend older than the caption fallback omits it
   *  entirely, and the gateway casts rather than validates. Absent means
   *  `full`. */
  completeness?: AnalysisCompleteness;
  error: string | null;
}

/** Deliberately has no `completeness`: `GET /api/runs` does not return one, and
 *  a history row cannot honestly claim a caveat it was never told about.
 *  Deriving one client-side would be inventing it. If history should mark
 *  caption-only runs, the backend has to send it here first. */
export interface RunSummary {
  run_id: string;
  status: RunStatus;
  title: string | null;
  created_at: string;
}

export interface RunListResponse {
  runs: RunSummary[];
}

export type MediaSource = { file: File; url?: never } | { url: string; file?: never };

/* ---- deployment capabilities (GET /api/capabilities) ----
   One row per dependency, answering "does this part of the deployment
   actually work right now, and was that actually checked?". See
   docs/backend/capabilities.md for what each row means.

   `state` and `name` are deliberately widened past the values the backend
   ships today: this endpoint exists to report the truth about a deployment,
   so a frontend that silently drops a row it does not recognise would be
   lying by omission the first time a probe is added. Unknown names render as
   themselves; unknown states render neutrally. */

/** The four states a capability row can report.
 *  `disabled` is NOT a fault — it is deployment shape (object storage
 *  unconfigured in local dev is normal) and the backend excludes it from the
 *  overall aggregation. Never render it as an error. */
export type CapabilityState = "ok" | "degraded" | "unavailable" | "disabled";

export interface Capability {
  name: string;
  state: CapabilityState | (string & {});
  detail: string;
  /** `false` means "we read configuration, we did not verify it". The honest
   *  core of the feature — surface it, never dress it up as a live check. */
  probed: boolean;
}

export interface CapabilityReport {
  /** The worst reported state with `disabled` excluded. */
  state: CapabilityState | (string & {});
  mode: "local" | "distributed" | (string & {});
  capabilities: Capability[];
}
