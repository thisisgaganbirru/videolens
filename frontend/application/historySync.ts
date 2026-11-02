import type {
  HistoryPatch,
  HistoryRecord,
  MediaSource,
  RunStatusResponse,
  RunSummary,
} from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import { historyStore, runsGateway } from "@/infrastructure/container";

/* Everything that writes History, in one place, free of React.

   History is this browser's own record (IndexedDB via `HistoryStore`). The
   server only holds a run until it is delivered — about an hour — so the
   browser files each run as it goes: on submit (queued), on every status
   change the poll reports, and in full (result, metadata, poster) once it is
   complete or failed.

   Every write here swallows its own failure. History is a convenience; a
   private window with no IndexedDB, or a quota error, must never be the
   reason an analysis does not show. */

/** Said on a run that was still in progress when this browser last saw it and
 *  that the server no longer has. Truthful: we do not know whether it would
 *  have finished, only that its result never reached this browser. */
export const EXPIRED_MESSAGE =
  "This run expired on the server before its result reached this browser.";

const IMPORT_FLAG = "videolens-history-imported";
const SNIPPET_MAX = 160;

function ignore(): void {}

/* ---------- mapping ---------- */

/** Same shape as the backend's `summary_snippet` (whitespace collapsed, cut at
 *  a word boundary, ellipsis), so a run filed here and one imported from the
 *  server search the same way. */
export function snippetOf(summary: string | null | undefined): string | null {
  if (!summary) return null;
  const text = summary.replace(/\s+/g, " ").trim();
  if (!text) return null;
  if (text.length <= SNIPPET_MAX) return text;
  let cut = text.slice(0, SNIPPET_MAX);
  const space = cut.lastIndexOf(" ");
  if (space > 0) cut = cut.slice(0, space);
  return `${cut.replace(/[\s.,;:!?-]+$/, "")}…`;
}

/** `data:image/jpeg;base64,...` → Blob. Null for anything else, so a
 *  malformed value from the wire is simply not stored. */
export function dataUrlToBlob(dataUrl: string | null | undefined): Blob | null {
  if (!dataUrl) return null;
  const match = /^data:(image\/[a-z+.-]+);base64,(.*)$/i.exec(dataUrl);
  if (!match) return null;
  try {
    const binary = atob(match[2]);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: match[1] });
  } catch {
    return null;
  }
}

/** A patch from one status response. Only what the response actually carries
 *  is written: a later response without a field never erases an earlier one. */
export function patchFromRun(run: RunStatusResponse): HistoryPatch {
  const patch: HistoryPatch = { run_id: run.run_id, status: run.status };
  if (run.source_kind) patch.source_kind = run.source_kind;
  if (run.platform) patch.platform = run.platform;
  if (typeof run.duration_seconds === "number") patch.duration_seconds = run.duration_seconds;
  if (typeof run.width === "number") patch.width = run.width;
  if (typeof run.height === "number") patch.height = run.height;
  if (run.orientation) patch.orientation = run.orientation;
  if (run.source_metadata) {
    patch.source_metadata = run.source_metadata;
    if (run.source_metadata.title) patch.title = run.source_metadata.title;
  }
  /* The poster is the server's, for links and uploads alike (cut from the
     normalised file, rotation applied). There is no browser-side frame grab:
     nothing shows a poster before the run is done. */
  const thumbnail = dataUrlToBlob(run.thumbnail);
  if (thumbnail) patch.thumbnail = thumbnail;
  if (run.status === "complete" && run.result) {
    patch.result = run.result;
    patch.completeness = run.completeness ?? "full";
    if (run.result.title?.trim()) patch.title = run.result.title;
    patch.summary_snippet = snippetOf(run.result.summary);
    patch.error = null;
  }
  if (run.status === "failed") patch.error = run.error || "Video analysis failed.";
  return patch;
}

function patchFromSummary(summary: RunSummary): HistoryPatch {
  const patch: HistoryPatch = {
    run_id: summary.run_id,
    status: summary.status,
    created_at: summary.created_at,
  };
  if (summary.title) patch.title = summary.title;
  if (summary.source_kind) patch.source_kind = summary.source_kind;
  if (summary.platform) patch.platform = summary.platform;
  if (typeof summary.duration_seconds === "number") patch.duration_seconds = summary.duration_seconds;
  if (summary.summary_snippet) patch.summary_snippet = summary.summary_snippet;
  if (summary.orientation) patch.orientation = summary.orientation;
  if (typeof summary.width === "number") patch.width = summary.width;
  if (typeof summary.height === "number") patch.height = summary.height;
  return patch;
}

/* ---------- writes from the analysis flow ---------- */

/** Filed the moment the server accepts a run. For an upload the browser
 *  already knows the kind of file; a link's platform comes from the server. */
export function recordSubmitted(runId: string, status: HistoryRecord["status"], source: MediaSource): void {
  const patch: HistoryPatch = {
    run_id: runId,
    status,
    created_at: new Date().toISOString(),
    source_kind: source.file ? "file" : "link",
  };
  if (source.url) patch.source_url = source.url;
  if (source.file) {
    patch.file_name = source.file.name;
    const audio = source.file.type.startsWith("audio/") || /\.mp3$/i.test(source.file.name);
    patch.platform = audio ? "audio_file" : "video_file";
  }
  historyStore.upsert(patch).catch(ignore);
}

/* Polls arrive every 3s with mostly the same answer. Writing (and making
   History re-read) only when something it shows changed keeps that quiet. */
const lastWritten = new Map<string, string>();

function signature(run: RunStatusResponse): string {
  return [run.status, run.thumbnail ? 1 : 0, run.width ?? "", run.platform ?? "", run.result ? 1 : 0].join("|");
}

/** File one observed status response. Called for every response the analysis
 *  screen applies (poll, reconnect, reopen). */
export function recordRunResponse(run: RunStatusResponse): void {
  if (!run?.run_id) return;
  const sig = signature(run);
  if (lastWritten.get(run.run_id) === sig) return;
  lastWritten.set(run.run_id, sig);
  historyStore.upsert(patchFromRun(run)).catch(() => lastWritten.delete(run.run_id));
}

/* ---------- once per app load ---------- */

let bootPromise: Promise<void> | null = null;

/** Import what the server still holds (first load only), then re-check any
 *  run this browser last saw unfinished. Idempotent per page load. */
export function bootHistory(): Promise<void> {
  if (!bootPromise) bootPromise = runBoot().catch(ignore);
  return bootPromise;
}

async function runBoot(): Promise<void> {
  /* Bail before touching the network if this browser cannot keep anything. */
  await historyStore.list();
  const imported = await importOnce();
  await reconcileUnfinished(imported);
}

function readFlag(): boolean {
  try {
    return window.localStorage.getItem(IMPORT_FLAG) === "1";
  } catch {
    return false;
  }
}

function writeFlag(): void {
  try {
    window.localStorage.setItem(IMPORT_FLAG, "1");
  } catch {
    /* no localStorage — the import may run again next load; harmless */
  }
}

/** One-time seed from `GET /api/runs`, for runs made before History moved
 *  into the browser. The flag is set only once the list actually came back,
 *  so a first load while offline tries again next time. After that the app
 *  never lists runs from the server again. Returns the ids it handled. */
async function importOnce(): Promise<Set<string>> {
  const handled = new Set<string>();
  if (readFlag()) return handled;
  let summaries: RunSummary[];
  try {
    summaries = (await runsGateway.listRuns()).runs;
  } catch {
    return handled;
  }
  writeFlag();
  for (const summary of summaries) {
    handled.add(summary.run_id);
    try {
      const existing = await historyStore.get(summary.run_id);
      if (existing?.result) continue;
      await historyStore.upsert(patchFromSummary(summary));
      const run = await runsGateway.getRun(summary.run_id);
      await historyStore.upsert(patchFromRun(run));
    } catch {
      /* silent: whatever made it in, made it in */
    }
  }
  return handled;
}

/** A run left queued/processing when the tab closed is asked about once. If
 *  the server has forgotten it (404 — past its one-hour hold), it is marked
 *  failed with a message that says so. Unreachable: left alone for later. */
async function reconcileUnfinished(skip: Set<string>): Promise<void> {
  const records = await historyStore.list();
  const unfinished = records.filter(
    (r) => (r.status === "queued" || r.status === "processing") && !skip.has(r.run_id)
  );
  for (const record of unfinished) {
    try {
      const run = await runsGateway.getRun(record.run_id);
      await historyStore.upsert(patchFromRun(run));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        await historyStore
          .upsert({ run_id: record.run_id, status: "failed", error: EXPIRED_MESSAGE })
          .catch(ignore);
      }
    }
  }
}
