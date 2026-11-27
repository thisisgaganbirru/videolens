import {
  ANONYMOUS_OWNER,
  isVisibleOwner,
  type HistoryPatch,
  type HistoryRecord,
  type MediaSource,
  type PostSlide,
  type RunStatusResponse,
  type RunSummary,
} from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import { readSlides } from "@/domain/slides";
import { authSession, callerIdentity, historyStore, runsGateway } from "@/infrastructure/container";

/* Everything that writes History, in one place, free of React.

   History is this browser's own record (IndexedDB via `HistoryStore`). The
   server only holds a run until it is delivered — about an hour — so the
   browser files each run as it goes: on submit (queued), on every status
   change the poll reports, and in full (result, metadata, poster) once it is
   complete or failed.

   Every write here swallows its own failure. History is a convenience; a
   private window with no IndexedDB, or a quota error, must never be the
   reason an analysis does not show.

   Two kinds of write (2026-11-20), so a signed-out device stays clear of an
   account's runs whichever tab or late answer is still busy:
   - **create** (`upsert`): only the run's first filing, on submit and on an
     import. It needs an owner, and an account's run is created only while
     that same account is signed in on this device, checked right before the
     write (`mayCreate`).
   - **update** (`HistoryStore.update`): everything after that (every poll,
     expiry, the reconcile at load, an import's detail). It merges into a row
     that is still there and never creates one, in the same transaction as
     its check, so a row removed in this tab or another is never written
     back.

   2026-11-21 (owner decision): signing out no longer removes an account's
   rows. They stay in this browser with their owner, hidden from History
   while that account is not the one signed in (`isVisibleOwner`), and shown
   again when it signs in here. Every update goes through `updateVisible`,
   which refuses, inside the write's transaction, a row hidden from whoever
   is signed in at that moment: a late poll for account A's run after A
   signed out neither shows it nor changes it, and no write ever changes a
   row's owner. Only deleting the account from this browser removes its
   rows (`forgetAccountRuns`). */

/** Said on a run that was still in progress when this browser last saw it and
 *  that the server no longer has. Truthful: we do not know whether it would
 *  have finished, only that its result never reached this browser. */
export const EXPIRED_MESSAGE =
  "This run expired on the server before its result reached this browser.";

/** Said on screen (never written to History) when the server answers 404 for
 *  a run this browser filed under a different identity: it was started signed
 *  in as someone else, or signed out, and the server holds it for that
 *  caller (auth phase 2). The run may be perfectly alive; the History row is
 *  left as it was, so switching back finds it again. */
export const OTHER_OWNER_MESSAGE =
  "This run was started under a different sign-in (or while signed out), so the server only shows it to that sign-in. Switch back to see it; it stays in your History.";

const IMPORT_FLAG = "videolens-history-imported";
const SNIPPET_MAX = 160;

function ignore(): void {}

/** Whether a run filed under `owner` belonged to an account rather than to
 *  this device's anonymous caller. Unknown (null) counts as an account's:
 *  privacy errs that way. Used for what is on Analyze, which a sign-out
 *  clears; History lists rows by `isVisibleOwner` instead. */
export function isAccountOwned(owner: string | null | undefined): boolean {
  return owner !== ANONYMOUS_OWNER;
}

/** The account signed in on this device right now, as a History owner
 *  (`user:<id>`), or null when nobody is (or a stored session could not be
 *  recovered yet, which shows only what is everyone's). Read at call time. */
export function historyViewer(): string | null {
  const id = authSession.hasSession() ? authSession.user()?.id : null;
  return id ? `user:${id}` : null;
}

/** Whether History may show (or change) a row filed under `owner` now. */
export function isVisibleNow(owner: string | null | undefined): boolean {
  return isVisibleOwner(owner, historyViewer());
}

/** An update that lands only on a row visible to whoever is signed in when
 *  the write happens (checked inside its transaction). */
function updateVisible(patch: HistoryPatch): Promise<boolean> {
  return historyStore.update(patch, (existing) => isVisibleNow(existing.owner));
}

/** Whether a row may be created for `owner` right now. Anonymous: yes. An
 *  account (`user:<id>`): only while that account is the one signed in on
 *  this device, read at write time, so a create that lands after a sign-out
 *  (here or in another tab, which the session hears) is dropped instead of
 *  being filed for someone no longer here. Unknown (null): never. */
function mayCreate(owner: string | null): owner is string {
  if (owner === ANONYMOUS_OWNER) return true;
  if (!owner || !isAccountOwner(owner)) return false;
  return owner === historyViewer();
}

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

/** Blob → `data:` URL, for showing a stored slide picture again. A data URL
 *  rather than an object URL so nothing has to be revoked; the CSP's
 *  `img-src` already allows `data:`. Null if the Blob cannot be read. */
export function blobToDataUrl(blob: Blob): Promise<string | null> {
  return new Promise((resolve) => {
    try {
      const reader = new FileReader();
      reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : null);
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    } catch {
      resolve(null);
    }
  });
}

/** A stored record's slide pictures, ready to show. Null for a record with
 *  none (reels, uploads, records written before 2026-11-27). A picture that
 *  cannot be read comes back null and is drawn as the placeholder. */
export async function slidesOfRecord(record: HistoryRecord): Promise<PostSlide[] | null> {
  if (!Array.isArray(record.slides) || record.slides.length === 0) return null;
  return Promise.all(
    record.slides.map(async (s) => ({
      slide: s.slide,
      kind: s.kind,
      thumbnail: s.thumbnail instanceof Blob ? await blobToDataUrl(s.thumbnail) : null,
    }))
  );
}

/** A patch from one status response. Only what the response actually carries
 *  is written: a later response without a field never erases an earlier one. */
export function patchFromRun(run: RunStatusResponse): HistoryPatch {
  const patch: HistoryPatch = { run_id: run.run_id, status: run.status };
  if (run.source_kind) patch.source_kind = run.source_kind;
  if (run.platform) patch.platform = run.platform;
  if (typeof run.duration_seconds === "number") patch.duration_seconds = run.duration_seconds;
  if (typeof run.slide_count === "number") patch.slide_count = run.slide_count;
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
  /* A carousel's slide pictures (2026-11-27), stored as Blobs like the
     poster so `list()`'s getAll does not copy them into memory as strings.
     They live in this browser only. The frontend never uploads a History
     record (see HistoryRecord.slides); Copy, Share and the .md report read
     `result`, which does not hold them. */
  const slides = readSlides(run.slides);
  if (slides) patch.slides = slides.map((s) => ({ ...s, thumbnail: dataUrlToBlob(s.thumbnail) }));
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
  if (typeof summary.slide_count === "number") patch.slide_count = summary.slide_count;
  if (summary.summary_snippet) patch.summary_snippet = summary.summary_snippet;
  if (summary.orientation) patch.orientation = summary.orientation;
  if (typeof summary.width === "number") patch.width = summary.width;
  if (typeof summary.height === "number") patch.height = summary.height;
  return patch;
}

/* ---------- writes from the analysis flow ---------- */

/** Filed the moment the server accepts a run. For an upload the browser
 *  already knows the kind of file; a link's platform comes from the server.
 *  `owner` is who the create request went out as (`AsOwner` from the
 *  gateway), taken from that request rather than from whatever went out
 *  last. */
export function recordSubmitted(
  runId: string,
  status: HistoryRecord["status"],
  source: MediaSource,
  owner: string | null
): void {
  if (forgotten.has(runId) || !mayCreate(owner)) return;
  const patch: HistoryPatch = {
    run_id: runId,
    status,
    created_at: new Date().toISOString(),
    source_kind: source.file ? "file" : "link",
  };
  /* Who the server holds it for. Always set: `mayCreate` refuses a null. */
  patch.owner = owner;
  if (source.url) patch.source_url = source.url;
  if (source.file) {
    patch.file_name = source.file.name;
    const audio = source.file.type.startsWith("audio/") || /\.mp3$/i.test(source.file.name);
    patch.platform = audio ? "audio_file" : "video_file";
  }
  historyStore.upsert(patch).catch(() => {
    /* The create did not land (quota, a transient IndexedDB error), so no
       row exists for any tab to update. This tab, and only this one, may
       try the create again with the next status it observes (2026-11-21). */
    if (!forgotten.has(runId)) unfiledCreates.set(runId, patch);
  });
}

/* Creates from this tab's own submits that failed, keyed by run id. In
   memory, so no other tab ever holds one: a row removed in another tab was
   a row this tab created, which takes it out of here, and the retry is
   checked with `mayCreate` like the first try. */
const unfiledCreates = new Map<string, HistoryPatch>();

/* Polls arrive every 3s with mostly the same answer. Writing (and making
   History re-read) only when something it shows changed keeps that quiet. */
const lastWritten = new Map<string, string>();

function signature(run: RunStatusResponse): string {
  return [
    run.status,
    run.thumbnail ? 1 : 0,
    run.width ?? "",
    run.platform ?? "",
    run.result ? 1 : 0,
    Array.isArray(run.slides) ? run.slides.length : 0,
  ].join("|");
}

/** File one observed status response. Called for every response the analysis
 *  screen applies (poll, reconnect, reopen). */
export function recordRunResponse(run: RunStatusResponse): void {
  if (!run?.run_id || forgotten.has(run.run_id)) return;
  const sig = signature(run);
  if (lastWritten.get(run.run_id) === sig) return;
  lastWritten.set(run.run_id, sig);
  const unfiled = unfiledCreates.get(run.run_id);
  if (unfiled) {
    /* This tab's own submit could not create the row: create it now, as
       the owner it was submitted as, and only while that owner may still
       create here (a sign-out since drops it for good). */
    if (!mayCreate(unfiled.owner ?? null)) {
      unfiledCreates.delete(run.run_id);
      return;
    }
    historyStore
      .upsert({ ...unfiled, ...patchFromRun(run) })
      .then(() => unfiledCreates.delete(run.run_id))
      .catch(() => lastWritten.delete(run.run_id));
    return;
  }
  /* An update only: the row was created on submit (or import). Gone since
     ("Remove from this device", account deletion, from any tab) means it
     stays gone; hidden from whoever is signed in now means it is left as it
     was. */
  updateVisible(patchFromRun(run))
    .then((updated) => {
      if (!updated) lastWritten.delete(run.run_id);
    })
    .catch(() => lastWritten.delete(run.run_id));
}

/** True when a gateway call failed because the server no longer has the run
 *  (HTTP 404 — past its hold, or lost to a restart of an in-memory store).
 *  Every other failure (offline, 5xx) says nothing about the run itself. */
export function isRunGone(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

/** Marks a run this browser knows about as expired: failed, with
 *  EXPIRED_MESSAGE. Used on every path that can meet the 404 — the live poll,
 *  a reconnect, reopening from History, and the startup reconcile — so the
 *  History row and the screen always agree. Resolves to the link the run was
 *  made from, when this browser stored one (for "Analyze it again"); null for
 *  an upload, or when History cannot be read. Never rejects. */
export async function recordExpired(runId: string): Promise<string | null> {
  lastWritten.delete(runId);
  try {
    /* An update: a run with no row here (removed, or never filed) gets
       none, and the link comes from whatever row is still there. A row
       hidden from whoever is signed in is neither changed nor read. */
    await updateVisible({ run_id: runId, status: "failed", error: EXPIRED_MESSAGE });
    const record = await historyStore.get(runId);
    if (!record || !isVisibleNow(record.owner)) return null;
    return record.source_url ?? record.source_metadata?.source_url ?? null;
  } catch {
    return null;
  }
}

/** What a 404 means for a run this browser knows. `expired`: the server
 *  forgot it, and History now says so (as `recordExpired`). `other-owner`:
 *  the record was filed under a different identity than the one the 404 was
 *  asked as, so the run is held for someone else and nothing is written. A
 *  record without an owner (written before auth) keeps the old rule. Never
 *  rejects. */
export type GoneOutcome = { kind: "expired"; againUrl: string | null } | { kind: "other-owner" };

export async function recordGone(runId: string): Promise<GoneOutcome> {
  const asked = callerIdentity.lastOwner();
  try {
    const record = await historyStore.get(runId);
    if (record?.owner && asked && record.owner !== asked) {
      lastWritten.delete(runId);
      return { kind: "other-owner" };
    }
  } catch {
    /* History unreadable: fall through to the old rule */
  }
  return { kind: "expired", againUrl: await recordExpired(runId) };
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
  let listed: { runs: RunSummary[]; owner: string | null };
  try {
    listed = await runsGateway.listRuns();
  } catch {
    return handled;
  }
  writeFlag();
  await importSummaries(listed.runs, listed.owner, handled);
  return handled;
}

/** Files each server-side run into History (skipping ones already holding a
 *  result), noting each id in `handled`. `owner` is who the list request
 *  went out as. Never rejects. */
async function importSummaries(summaries: RunSummary[], owner: string | null, handled: Set<string>): Promise<void> {
  for (const summary of summaries) {
    handled.add(summary.run_id);
    if (forgotten.has(summary.run_id)) continue;
    try {
      const existing = await historyStore.get(summary.run_id);
      if (existing?.result) continue;
      const patch = patchFromSummary(summary);
      if (existing) {
        /* A row this browser already filed keeps the owner it was filed
           with; one that was legacy (no owner) takes the list's. */
        if (owner && !existing.owner && mayCreate(owner)) patch.owner = owner;
        if (!(await updateVisible(patch))) continue;
      } else {
        /* A new row: filed for the identity the list request went out as,
           and only while that identity is still the one here. */
        if (!mayCreate(owner)) continue;
        patch.owner = owner;
        await historyStore.upsert(patch);
      }
      const run = await runsGateway.getRun(summary.run_id);
      /* An update: a sign-out during the fetch has hidden the row. */
      await updateVisible(patchFromRun(run));
    } catch {
      /* silent: whatever made it in, made it in */
    }
  }
}

let identityImport: Promise<void> | null = null;

/** Auth phase 2: the caller changed (someone signed in, or a different
 *  person did), so the server's run owner changed with it. Asks
 *  `GET /api/runs` again, now as the new identity, and files any run it holds
 *  that this browser has not got: a run the same person started on another
 *  device, or through an API key, within the server's one-hour hold. Runs
 *  already in History stay whoever made them; History is the browser's.
 *  One at a time; never rejects. */
export function importServerRuns(): Promise<void> {
  if (!identityImport) {
    identityImport = (async () => {
      try {
        await bootHistory();
        const listed = await runsGateway.listRuns();
        const handled = new Set<string>();
        await importSummaries(listed.runs, listed.owner, handled);
        /* 2026-11-21: this account's rows were hidden, not removed, while it
           was signed out, and nothing updated them meanwhile. One left
           unfinished that the server no longer lists is asked about now, as
           the boot reconcile would. */
        const viewer = historyViewer();
        if (viewer && listed.owner === viewer) await reconcileUnfinished(handled, viewer);
      } catch {
        /* offline, or the server forgot: History is unchanged */
      }
    })().finally(() => {
      identityImport = null;
    });
  }
  return identityImport;
}

/* ---------- leaving this device ---------- */

/* Ids removed from this device during this page load. A poll or an import
   already in flight when the row went must not file it again, so every write
   above checks this first. In memory only: after a reload nothing is in
   flight. */
const forgotten = new Set<string>();

function isAccountOwner(owner: string): boolean {
  return owner.startsWith("user:");
}

/** "Remove from this device" on one History row. Only this browser's copy
 *  goes; a copy saved to the account (paid plan) is not touched. Rejects when
 *  the store refused the delete, so the dialog can say so. */
export async function forgetRun(runId: string): Promise<void> {
  forgotten.add(runId);
  lastWritten.delete(runId);
  try {
    await historyStore.remove(runId);
  } catch (error) {
    /* The row is still there, so it must keep updating like any other; the
       caller says the removal failed. */
    forgotten.delete(runId);
    throw error;
  }
}

/** The account `userId` was deleted from this browser (2026-11-21): its rows
 *  (`owner` `user:<userId>`) leave this device, since nobody could ever sign
 *  in to see them again once the deletion completes. Only that account's:
 *  anonymous rows, rows with no owner and other accounts' hidden rows stay.
 *  A plain sign-out never calls this; it only hides the rows. Waits for an
 *  identity import still filing rows first. Never rejects. */
export async function forgetAccountRuns(userId: string): Promise<void> {
  const owner = `user:${userId}`;
  try {
    if (identityImport) await identityImport;
  } catch {
    /* the import never rejects; belt and braces */
  }
  try {
    const records = await historyStore.list();
    for (const record of records) {
      if (record.owner === owner) {
        forgotten.add(record.run_id);
        lastWritten.delete(record.run_id);
        unfiledCreates.delete(record.run_id);
      }
    }
  } catch {
    /* storage unavailable: nothing is kept here to forget */
  }
  try {
    await historyStore.removeOwnedBy((candidate) => candidate === owner);
  } catch {
    /* a refused delete leaves the rows, hidden like any signed-out account's */
  }
}

/** A run left queued/processing when the tab closed is asked about once. If
 *  the server has forgotten it (404 — past its one-hour hold), it is marked
 *  failed with a message that says so. Unreachable: left alone for later. */
async function reconcileUnfinished(skip: Set<string>, onlyOwner?: string): Promise<void> {
  /* Who is signed in must be known before rows are picked by it. */
  await authSession.load().catch(ignore);
  const records = await historyStore.list();
  const unfinished = records.filter(
    (r) =>
      (r.status === "queued" || r.status === "processing") &&
      !skip.has(r.run_id) &&
      isVisibleNow(r.owner) &&
      (onlyOwner === undefined || r.owner === onlyOwner)
  );
  for (const record of unfinished) {
    try {
      const run = await runsGateway.getRun(record.run_id);
      /* An update: hidden by a sign-out while the answer was on its way
         means left alone. */
      await updateVisible(patchFromRun(run));
    } catch (err) {
      if (isRunGone(err)) await recordGone(record.run_id);
    }
  }
}
