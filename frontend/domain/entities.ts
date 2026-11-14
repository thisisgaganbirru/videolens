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

/** How a run's media arrived. The server's word on it, recorded at create
 *  time — the authority wherever it is present. Absent on runs stored before
 *  the field existed. */
export type RunSourceKind = "link" | "file";

/** Where a run's media came from, as the backend classifies it. `other` is a
 *  link to a site with no dedicated label. */
export type RunPlatform = "youtube" | "instagram" | "tiktok" | "audio_file" | "video_file" | "other";

export type RunOrientation = "landscape" | "portrait";

export interface RunStatusResponse {
  run_id: string;
  status: RunStatus;
  stage: string | null;
  result: VideoAnalysis | null;
  /* Optional: older stored runs (and older backends) omit all three. */
  source_kind?: RunSourceKind | null;
  platform?: RunPlatform | null;
  duration_seconds?: number | null;
  source_metadata?: SourceMetadata | null;
  /** Optional on the wire: a backend older than the caption fallback omits it
   *  entirely, and the gateway casts rather than validates. Absent means
   *  `full`. */
  completeness?: AnalysisCompleteness;
  error: string | null;
  /** Phase 5a. A `data:image/jpeg;base64,...` poster (<= ~20 KB) and the
   *  display size with rotation applied. All optional: audio runs, older runs
   *  and older backends have none. The browser files them into its History. */
  thumbnail?: string | null;
  width?: number | null;
  height?: number | null;
  orientation?: RunOrientation | null;
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
  /* Phase 3 (History poster grid). Every one is optional AND nullable: runs
     stored before these fields existed come back without them, and the
     gateway casts rather than validates. The poster renders each piece only
     when it is actually present — see components/history.ts. */
  source_kind?: RunSourceKind | null;
  platform?: RunPlatform | null;
  duration_seconds?: number | null;
  /** The first lines of the summary, for client-side search only. */
  summary_snippet?: string | null;
  /** Absent means portrait: most runs are short vertical clips. */
  orientation?: RunOrientation | null;
  /** Display size, when the backend measured it. Wider than tall = landscape. */
  width?: number | null;
  height?: number | null;
}

/** One run as this browser's History keeps it (IndexedDB, newest 20).
 *
 *  Everything needed to list it AND to reopen it with no network: the summary
 *  fields the poster grid reads, the poster itself as a Blob, and the full
 *  delivered result. The server forgets a run about an hour after it is
 *  created; this record is what survives that. Nullable throughout because a
 *  run is written the moment the server accepts it, long before most of these
 *  are known. */
export interface HistoryRecord {
  run_id: string;
  /** ISO timestamp. Client clock for runs started here, the server's for
   *  runs imported from it. The cap drops the oldest by this. */
  created_at: string;
  status: RunStatus;
  title: string | null;
  source_kind: RunSourceKind | null;
  platform: RunPlatform | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  orientation: RunOrientation | null;
  summary_snippet: string | null;
  /** The server's JPEG poster (longest side <= 320px, <= ~20 KB), stored as
   *  a Blob. Null for audio, failed runs, and until the server has one. */
  thumbnail: Blob | null;
  result: VideoAnalysis | null;
  source_metadata: SourceMetadata | null;
  completeness: AnalysisCompleteness | null;
  error: string | null;
  /** The link as submitted from this browser (refinement 1, #7), so a run the
   *  server forgot can be offered again with the field filled. Null for
   *  uploads and imported runs; absent on records written before it existed.
   *  Stays in IndexedDB — never sent anywhere new. */
  source_url?: string | null;
  /** The uploaded file's name as picked in this browser (refinement 2, #6),
   *  for the result's Source card. The server never keeps it. Null for links
   *  and imported runs; absent on records written before it existed. */
  file_name?: string | null;
  /** Who the server holds this run for, as the request that created (or
   *  imported) it went out: `user:<id>` or `anonymous` (auth phase 2). A 404
   *  under a different identity means "not yours right now", not "expired",
   *  so the row is left alone. Absent on records written before it existed;
   *  those keep the old 404-means-expired rule. */
  owner?: string | null;
  updated_at: string;
}

/** A partial write: `run_id` plus whichever fields are now known. Fields left
 *  `undefined` keep their stored value. */
export type HistoryPatch = Partial<HistoryRecord> & { run_id: string };

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

/** This device's free-run allowance for the current UTC day, from
 *  `GET /api/free-runs`. Only meaningful without a bring-your-own key: a
 *  caller with their own Gemini key has no limit and never sees it. */
export interface FreeRunsStatus {
  /** The random, server-issued token that counts this device's runs. Not tied
   *  to a person. Replaced whenever the server answers with a different one. */
  deviceToken: string;
  limit: number;
  used: number;
  remaining: number;
  /** ISO 8601 UTC instant the count resets (next UTC midnight). */
  resetsAt: string;
  /** `false`: the deployment has no free-run limit — show nothing. */
  enabled: boolean;
}

/* ---- accounts (auth phase 2; contract in docs/backend/auth.md) ----
   Sign-in is optional. A deployment without an identity provider never
   produces any of these. Field names follow the API's JSON, as the run
   shapes above do. */

/** The person the identity provider says is signed in. Provider-neutral:
 *  nothing outside `infrastructure/authSession.ts` knows it is Supabase. */
export interface AuthUser {
  /** The provider's stable user id (the token's `sub`). */
  id: string;
  email: string | null;
}

export interface AccountWorkspace {
  workspace_id: string;
  name: string;
}

/** What the caller may do. One free plan in this phase; the numbers are the
 *  deployment's own limits. */
export interface AccountEntitlement {
  plan: string;
  max_duration_seconds: number;
  max_file_size_mb: number;
  metered: boolean;
  api_access: boolean;
  library: boolean;
}

/** `GET /api/me`. Identity and entitlement, no usage and no plan cards. */
export interface AccountResponse {
  subject: string;
  method: "token" | "api_key" | "anonymous" | (string & {});
  email: string | null;
  account_id: string | null;
  workspace: AccountWorkspace | null;
  entitlement: AccountEntitlement;
  /** False when the server has nowhere to keep accounts: sign-in works, but
   *  there is no workspace and `/api/keys` answers 503. */
  accounts_enabled: boolean;
}

/** A VideoLens API key as a listing shows it. Never carries the secret. */
export interface ApiKeySummary {
  key_id: string;
  name: string;
  /** `vl_live_` plus the first eight characters, kept so a key is recognisable. */
  prefix: string;
  scopes: string[];
  active: boolean;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** The one response that carries a key's secret. Shown once, never stored. */
export interface ApiKeyCreated extends ApiKeySummary {
  secret: string;
}

export interface ApiKeyListResponse {
  keys: ApiKeySummary[];
}
