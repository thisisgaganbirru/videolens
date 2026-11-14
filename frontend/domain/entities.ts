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

/** Whose allowance a free-run count is. `device`: this device's few runs
 *  per UTC day (anonymous). `account`: the signed-in account's runs, shared
 *  across that person's devices and used *instead of* the device's while
 *  signed in (2026-11-13); per UTC day on both plans since 2026-11-14. A server that predates the account allowance
 *  sends no scope, which reads as `device`. */
export type FreeRunsScope = "device" | "account";

/** The period a run allowance counts over (2026-11-14). `day`: resets at
 *  the next UTC midnight (anonymous devices, free accounts and, since
 *  2026-11-14, the paid plan's 30). `month`: kept for a server that still
 *  counts the paid plan per month. */
export type FreeRunsPeriod = "day" | "month";

/** The free-run allowance the server counts this caller against, from
 *  `GET /api/free-runs`: this device's for the UTC day, or (signed in) the
 *  account's for the UTC day. Only meaningful without a bring-your-own key:
 *  a caller with their own Gemini key has no limit and never sees it. */
export interface FreeRunsStatus {
  /** `device` or `account`; see `FreeRunsScope`. */
  scope: FreeRunsScope;
  /** The signed-in account's plan (2026-11-13, one paid plan). `paid` counts
   *  against the paid daily allowance (`limit`, 30 since 2026-11-14). A server
   *  without billing sends no plan, which reads as `free`. */
  plan: BillingPlan;
  /** What the count resets over (`period` on the response, 2026-11-14). A
   *  server that does not send it reads as `day`. */
  period: FreeRunsPeriod;
  /** Paid only: runs past `limit` are allowed and billed per run, so a spent
   *  allowance does not block. `false` everywhere else. */
  overage: boolean;
  /** Complimentary Plus (2026-11-14): the account was put on the paid plan
   *  by hand, with no subscription. `plan` is then `paid`, `overage` false,
   *  and nothing is for sale to it. `false` from older servers. */
  complimentary: boolean;
  /** The random, server-issued token that counts this device's runs. Not tied
   *  to a person. Replaced whenever the server answers with a different one. */
  deviceToken: string;
  limit: number;
  used: number;
  remaining: number;
  /** ISO 8601 UTC instant the count resets: next UTC midnight (`day`), or
   *  the start of the next month (`month`, an older paid server). */
  resetsAt: string;
  /** `false`: the deployment has no free-run limit — show nothing. */
  enabled: boolean;
}

/** How long and how large one upload may be (`GET /api/limits`,
 *  2026-11-13). The server enforces these regardless; the client reads them
 *  only to word the intake and to refuse a file before uploading it. */
export interface MediaLimits {
  maxDurationSeconds: number;
  maxFileSizeMb: number;
}

/** Both tiers the server reports. `signedInByok` applies to a signed-in
 *  person running on their own Gemini key; everyone else gets `standard`.
 *  On a server without the endpoint both are today's standard values. */
export interface MediaLimitsTable {
  standard: MediaLimits;
  signedInByok: MediaLimits;
  /** The paid plan's limits, which need no key; null from a server that does
   *  not report them (then the paid plan gets the other tiers' rules). */
  paid: MediaLimits | null;
}

/* ---- billing (2026-11-13, "Level 3, one paid plan") ----
   Stripe hosted Checkout and Customer Portal, reached by redirect; the
   browser never loads Stripe.js and never sees a card. `GET /api/billing`
   describes the signed-in account's plan. Field names here are camelCase
   because the adapter normalises the body (it is optional chrome). */

export type BillingPlan = "free" | "paid";
export type BillingInterval = "month" | "year";

/** A price in the currency's minor units (cents for usd), as Stripe gives it. */
export interface BillingPrice {
  amount: number;
  currency: string;
}

export interface BillingPrices {
  month: BillingPrice | null;
  year: BillingPrice | null;
  /** Each run past the paid daily allowance (capped per month). */
  extraRun: BillingPrice | null;
}

/** The paid plan's extra runs over the calendar month (UTC). `used` is what
 *  the monthly cap counts; `limit` is that cap, or null when the server has
 *  the cap off. */
export interface BillingExtraRuns {
  used: number;
  limit: number | null;
  period: "month";
  /** ISO 8601: 00:00 UTC on the first of next month. */
  resetsAt: string | null;
}

/** `GET /api/billing`. `enabled: false` means there is no plan to describe
 *  (the server has billing off and the account is an ordinary one), and the
 *  app then looks exactly as it did before billing existed. `enabled: true`
 *  here means the body describes a plan: Stripe billing is on (`stripe`), or
 *  the account has complimentary Plus (2026-11-14), which the server
 *  describes even with Stripe off. */
export type BillingStatus =
  | { enabled: false }
  | {
      enabled: true;
      /** The server's own `enabled`: Stripe billing is on, so the plan can
       *  be bought and managed. False only on a complimentary body. */
      stripe: boolean;
      /** Complimentary Plus: on the paid plan with no subscription. Nothing
       *  to buy, manage or bill; `plan` is `paid`. */
      complimentary: boolean;
      plan: BillingPlan;
      /** Stripe's subscription status (`active`, `past_due`, `canceled`, ...);
       *  null on the free plan. Kept as a string: an unknown value renders
       *  neutrally rather than being dropped. */
      status: string | null;
      interval: BillingInterval | null;
      /** ISO 8601; the renewal date, or the end date when cancelling. */
      currentPeriodEnd: string | null;
      cancelAtPeriodEnd: boolean;
      /** `period` (2026-11-14): `day` on both plans now; a body without it
       *  reads as `day`. */
      runs: { limit: number; used: number; period: FreeRunsPeriod };
      /** Billed extra runs this UTC month (2026-11-14). Null on the free
       *  plan, and when an older server sends no field or an unreadable one,
       *  so the Billing card simply leaves the row out. */
      extraRuns: BillingExtraRuns | null;
      prices: BillingPrices;
    };

/** A plan the server actually sells: `BillingStatus` with billing on. */
export type BillingDetails = Extract<BillingStatus, { enabled: true }>;

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
  /** Complimentary Plus (2026-11-14): `plan` reads `paid` with no
   *  subscription. Absent on older servers. */
  complimentary?: boolean;
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
  /** Paid saved history (2026-11-14). Absent on older backends. */
  saved_history?: SavedHistoryStatus | null;
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

/* ---- saved history (paid, 2026-11-14; contract in docs/backend/saved-history.md) ----
   A paid account's successful runs are saved on the server. Every field is
   optional-tolerant: an older backend has no `/api/history` (404) and no
   `saved_history` on `/api/me`, and the gateways cast rather than validate. */

/** Whether the account is saving runs now, and when its saved runs are
 *  removed after a plan ended (ISO, or null while paid / never paid). */
export interface SavedHistoryStatus {
  saving: boolean;
  expires_at: string | null;
}

/** What the server kept about where a saved run came from. Any field may be
 *  null; a file run has no `source_url` (the server never keeps a name). */
export interface SavedRunSource {
  source_kind?: RunSourceKind | null;
  platform?: RunPlatform | null;
  source_url?: string | null;
  source_title?: string | null;
  uploader?: string | null;
  duration_seconds?: number | null;
  width?: number | null;
  height?: number | null;
}

/** One saved run as `GET /api/history` lists it: light fields only. */
export interface SavedRunSummary {
  run_id: string;
  title: string | null;
  summary_snippet?: string | null;
  completeness?: AnalysisCompleteness | string | null;
  created_at: string;
  source?: SavedRunSource | null;
  /** The poster, same shape as a finished run's `thumbnail`: a
   *  `data:image/jpeg;base64,...` URL (<= ~20 KB) or null. Absent on a
   *  backend that predates it. */
  thumbnail?: string | null;
}

export interface SavedRunPage extends SavedHistoryStatus {
  items: SavedRunSummary[];
  next_cursor: string | null;
}

/** `GET /api/history/{run_id}`: the summary plus the full saved result. */
export interface SavedRunDetail extends SavedRunSummary {
  result: VideoAnalysis;
}

/** `DELETE /api/me` (2026-11-14): the account is held, not removed. Null
 *  `purgeAt` from an older backend that answered 204 and removed it at once. */
export interface AccountDeletionOutcome {
  purgeAt: string | null;
}
