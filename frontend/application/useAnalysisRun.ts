"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AnalysisCompleteness,
  FreeRunsStatus,
  MediaSource,
  RunStatus,
  RunSourceKind,
  RunStatusResponse,
  SourceMetadata,
  VideoAnalysis,
} from "@/domain/entities";
import { classifyGatewayError } from "@/application/gatewayError";
import {
  EXPIRED_MESSAGE,
  isRunGone,
  OTHER_OWNER_MESSAGE,
  recordGone,
  recordRunResponse,
  recordSubmitted,
} from "@/application/historySync";
import {
  currentFreeRuns,
  markFreeRunsUsed,
  noteRunAccepted,
  refreshFreeRuns,
  revalidateFreeRuns,
  usingOwnKey,
} from "@/application/useFreeRuns";
import { ApiError } from "@/domain/errors";
import { activeRunStore, apiKeyStore, historyStore, runsGateway, sharedUrlSource } from "@/infrastructure/container";

const POLL_INTERVAL_MS = 3000;

/* Reconnect schedule after a poll throws: 4s, 8s, 16s, then every 30s until the
   user starts over. The first wait is short because most drops are a blip (a
   phone changing networks); the cap keeps a genuinely offline tab from
   hammering the server the moment it comes back, without ever giving up on a
   run that is still finishing server-side. */
const RECONNECT_DELAYS_S = [4, 8, 16, 30];

function reconnectDelay(attempt: number): number {
  return RECONNECT_DELAYS_S[Math.min(attempt, RECONNECT_DELAYS_S.length - 1)];
}

/** The full wait scheduled for the given 1-based `reconnectAttempt`, so the
 *  screen can announce "trying again in N seconds" once per attempt without
 *  reading the ticking countdown. */
export function reconnectDelayFor(reconnectAttempt: number): number {
  return reconnectDelay(Math.max(0, reconnectAttempt - 1));
}

/* What the progress screen calls the thing being analyzed before the server has
   said anything about it: the link as typed (minus the scheme), or the file's
   own name. Display only — never sent anywhere. */
function describeSource(source: MediaSource): string {
  if (source.file) return source.file.name;
  return source.url.replace(/^https?:\/\/(www\.)?/i, "").replace(/\/$/, "");
}

/* Fallbacks only — they are reached when the failure is neither a `NetworkError`
   nor an `ApiError`, i.e. when we genuinely do not know. A backend that is down
   gets the gateway's connectivity sentence and a backend that answered gets its
   own `detail`; describing either as "could not submit media" was the same
   dishonesty already fixed in `useRunHistory`. */
const SUBMIT_FALLBACK = "Could not submit media.";
const OPEN_FALLBACK = "Could not load that run.";
const POLL_FALLBACK = "Something went wrong.";

/** Why the poll is down (refinement 6, RUN-08). `network`: no answer at all
 *  (offline, refused, DNS). `server`: the server answered, with an error
 *  (a 5xx, or a body this app could not read). Same reconnect either way;
 *  the screen just says the true thing. A 404 is neither: it is "expired". */
export type LostCause = "network" | "server";

/** What is being analyzed, for the progress copy (refinement 9): an mp3 run
 *  used to read "Reading your video". `null` when nothing says (a link to a
 *  site with no dedicated label, a reopened legacy run): the copy then names
 *  neither. */
export type MediaKind = "audio" | "video";

const AUDIO_EXTENSIONS = [".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"];

function mediaKindOfSource(source: MediaSource): MediaKind | null {
  if (source.file) {
    const name = source.file.name.toLowerCase();
    if (source.file.type.startsWith("audio/") || AUDIO_EXTENSIONS.some((ext) => name.endsWith(ext))) return "audio";
    return "video";
  }
  /* The three platforms the intake names are video platforms; anything else
     waits for the server's `platform`. */
  try {
    const host = new URL(source.url).hostname.replace(/^www\./, "");
    if (/(^|\.)(youtube\.com|youtu\.be|instagram\.com|tiktok\.com)$/.test(host)) return "video";
  } catch {
    /* not a URL; say nothing */
  }
  return null;
}

/** The server's word on the media, from the run's `platform`. */
function mediaKindOfPlatform(platform: string | null | undefined): MediaKind | null {
  if (platform === "audio_file") return "audio";
  if (platform === "video_file" || platform === "youtube" || platform === "instagram" || platform === "tiktok") {
    return "video";
  }
  return null;
}

/* Refinement 9 (item 8): the backend refunds the free run when a link fails to
   download or fails the duration cap after downloading. The app says "this
   didn't use a free run" ONLY when the server's own count proves it: the
   remaining count is back to what it was just before the submit, within the
   same UTC day (an unchanged `resetsAt`, so a midnight reset cannot pose as a
   refund). The refund is written just after the failure is (process_run's
   `finally`), so one late re-read covers the poll that lands between them. */
const REFUND_RECHECK_MS = 2500;

function provesRefund(before: FreeRunsStatus, after: FreeRunsStatus | null): boolean {
  return (
    after !== null &&
    before.enabled &&
    after.enabled &&
    /* A sign-in or sign-out between the two reads swaps whose count it is. */
    after.scope === before.scope &&
    after.resetsAt === before.resetsAt &&
    after.remaining === before.remaining
  );
}

function lostCauseOf(err: unknown): LostCause {
  return classifyGatewayError(err, POLL_FALLBACK).kind === "server" ? "server" : "network";
}

export function useAnalysisRun() {
  const [status, setStatus] = useState<RunStatus | "idle">("idle");
  const [stage, setStage] = useState<string | null>(null);
  const [sourceKind, setSourceKind] = useState<"file" | "url">("file");
  const [mediaKind, setMediaKind] = useState<MediaKind | null>(null);
  /* Item 8: set only when the re-read count proves the failed run was not
     charged (see provesRefund). Never set on the user's own key. */
  const [freeRunRefunded, setFreeRunRefunded] = useState(false);
  const [result, setResult] = useState<VideoAnalysis | null>(null);
  /* Set only alongside `result`, never on a `processing` tick. It describes
     what the finished analysis was able to look at, so it is meaningless
     before there is one and would otherwise read `full` (the wire default)
     while the run was still deciding. */
  const [completeness, setCompleteness] = useState<AnalysisCompleteness>("full");
  const [sourceMetadata, setSourceMetadata] = useState<SourceMetadata | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  /* The link or file name of the run on screen, for the progress view's source
     chip. Known only for runs submitted in this session; a run reopened from
     History has none until its metadata arrives. */
  const [sourceName, setSourceName] = useState<string | null>(null);
  /* The media's length, from the run detail (or the History record), for the
     Source card of a file run (refinement 2, #6). */
  const [durationSeconds, setDurationSeconds] = useState<number | null>(null);
  /* The last submitted source, kept so a failed run can be retried with one
     press instead of re-pasting or re-picking. State rather than a ref because
     the screen reads it (whether to offer "Try again") during render. Cleared
     by reset and openRun — a run reopened from History has nothing to resubmit. */
  const [retrySource, setRetrySource] = useState<MediaSource | null>(null);
  /* Connection-lost bookkeeping. `reconnectIn` is whole seconds until the next
     automatic attempt (ticks once a second, for the visible countdown);
     `reconnecting` is true while an attempt is on the wire; `reconnectAttempt`
     counts failed attempts since the connection was last good and changes once
     per attempt — the polite announcement keys on it, so a screen reader hears
     one sentence per attempt rather than one per second. */
  const [reconnectIn, setReconnectIn] = useState<number | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const [lostCause, setLostCause] = useState<LostCause>("network");
  /* Refinement 1, #7: the run on screen is one the server forgot before its
     result reached this browser (History's EXPIRED_MESSAGE). Nothing about the
     source was wrong, so the failed view drops its "try a different link"
     advice and offers to analyze it again. `againUrl` is the link to put back
     in the field, when this browser stored one. */
  const [expired, setExpired] = useState<{ againUrl: string | null } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const runIdRef = useRef<string | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const attemptRef = useRef(0);
  /* Mirrors `submitting` for the guard below. State is read from a stale
     closure inside the same tick a second submit could arrive in; a ref is
     read at call time, which is what a re-entrancy guard needs. */
  const submittingRef = useRef(false);
  /* The link of the run being watched live, when it was submitted from a link
     in this session — what "Analyze it again" puts back if the server forgets
     the run mid-flight (refinement 3, #1). A ref because the poll's closure
     reads it; History holds the same value, but may be unavailable. */
  const liveUrlRef = useRef<string | null>(null);
  /* Bumped by every intent that replaces what is on screen — `submit`,
     `openRun`, `reset`. A request that was already in flight when the next
     intent arrived resolves into a screen that has moved on, so each one drops
     its result if the counter no longer matches the value it captured. Without
     it, a link shared mid-submit is undone a moment later by the 202 for the
     run the user just abandoned. The reconnect timers check it too. */
  const generationRef = useRef(0);
  /* The free-run allowance just before the live run was submitted, or null
     (own key, unknown, or a run reopened from History). Consumed by the
     failure check, so it is used at most once per submit. */
  const freeRunsBeforeRef = useRef<FreeRunsStatus | null>(null);
  const refundTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* Every timer this hook owns, stopped in one place: unmount, reset, openRun,
     a fresh submit and a successful reconnect all need exactly this. */
  const stopTimers = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    if (tickRef.current) clearInterval(tickRef.current);
    if (refundTimerRef.current) clearTimeout(refundTimerRef.current);
    pollRef.current = null;
    reconnectTimerRef.current = null;
    tickRef.current = null;
    refundTimerRef.current = null;
  }, []);

  /* Unmount also retires the generation, so a request still in flight (a
     resume started by a render that is being replaced) cannot write History
     or the active-run marker on its way back. */
  useEffect(
    () => () => {
      stopTimers();
      generationRef.current += 1;
    },
    [stopTimers]
  );

  const clearReconnect = useCallback(() => {
    attemptRef.current = 0;
    setReconnectIn(null);
    setReconnecting(false);
    setReconnectAttempt(0);
    setLostCause("network");
  }, []);

  const fail = useCallback((err: unknown, fallback: string) => {
    setError(classifyGatewayError(err, fallback).message);
  }, []);

  /* A run settled. Re-read the allowance either way (refinement 9, item 6),
     and for a failed live run, check whether it was refunded (item 8). */
  const settleFreeRuns = useCallback((failed: boolean) => {
    const before = freeRunsBeforeRef.current;
    freeRunsBeforeRef.current = null;
    const generation = generationRef.current;
    const check = (after: FreeRunsStatus | null) => {
      if (generationRef.current !== generation || !before || usingOwnKey()) return false;
      if (!provesRefund(before, after)) return false;
      setFreeRunRefunded(true);
      return true;
    };
    void revalidateFreeRuns().then((after) => {
      if (!failed || !before || check(after)) return;
      if (generationRef.current !== generation) return;
      refundTimerRef.current = setTimeout(() => {
        refundTimerRef.current = null;
        void revalidateFreeRuns().then(check);
      }, REFUND_RECHECK_MS);
    });
  }, []);

  /* One observed run response, applied to the screen. Returns true when the
     run has settled (complete or failed) — nothing left to poll for. Shared by
     the interval, a reconnect attempt and openRun so the three cannot disagree
     about what a response means. */
  const applyRun = useCallback((run: RunStatusResponse): boolean => {
    /* Every response the screen applies is also filed into this browser's
       History — that is how a run survives the server forgetting it. */
    recordRunResponse(run);
    setStatus(run.status);
    setStage(run.stage);
    const kind = mediaKindOfPlatform(run.platform);
    if (kind) setMediaKind(kind);
    if (run.source_metadata) setSourceMetadata(run.source_metadata);
    if (typeof run.duration_seconds === "number") setDurationSeconds(run.duration_seconds);
    /* `source_kind` is the server's record of how the run arrived, so when
       the response carries it, it decides — both ways. Runs stored before the
       field existed omit it; only then does the old inference apply: source
       metadata and these two stages only ever exist for link runs, so either
       one settles it (otherwise the progress strip would draw "File received"
       over a link). The inference never flips a link run back to "file". */
    if (run.source_kind === "link") {
      setSourceKind("url");
    } else if (run.source_kind === "file") {
      setSourceKind("file");
    } else if (run.source_metadata || run.stage === "downloading" || run.stage === "analyzing_captions") {
      setSourceKind("url");
    }
    if (run.status === "complete") {
      activeRunStore.clear();
      setResult(run.result);
      setCompleteness(run.completeness ?? "full");
      settleFreeRuns(false);
      return true;
    }
    if (run.status === "failed") {
      activeRunStore.clear();
      setError(run.error || "The analysis failed.");
      settleFreeRuns(true);
      return true;
    }
    return false;
  }, [settleFreeRuns]);

  /* Refinement 3, #1: the server answered 404 for a run this browser knows
     about — it forgot the run (past its hold, or a restart of an in-memory
     store). That is final, not a lost connection: stop every timer, file the
     History row as expired, and show the expired view with its normal
     actions. `knownUrl` is the link when the caller already has it; otherwise
     the one History stored is used once the write lands. */
  /* Auth phase 2: a 404 for a run History filed under a different identity
     (signed in as someone else, or signed out) is not an expiry. The server
     holds it for that caller; the screen says so and History is not
     touched, so switching back finds the run again (`recordGone`). */
  const expireRun = useCallback(
    async (runId: string, generation: number, knownUrl: string | null) => {
      stopTimers();
      clearReconnect();
      activeRunStore.clear();
      const outcome = await recordGone(runId);
      if (generationRef.current !== generation) return;
      setStatus("failed");
      setStage(null);
      if (outcome.kind === "other-owner") {
        setError(OTHER_OWNER_MESSAGE);
        setExpired(null);
        return;
      }
      setError(EXPIRED_MESSAGE);
      setExpired({ againUrl: knownUrl ?? outcome.againUrl });
    },
    [clearReconnect, stopTimers]
  );

  /* `startPolling` and `scheduleReconnect` reach each other (a dead poll
     schedules a reconnect; a good reconnect resumes polling), so the second is
     called through a ref rather than a dependency cycle. */
  const scheduleReconnectRef = useRef<(generation: number) => void>(() => {});

  const startPolling = useCallback(
    (runId: string, generation: number) => {
      runIdRef.current = runId;
      /* Refinement 6 (RUN-06 web): this tab is now watching `runId`; a reload
         before it settles picks it back up (see `resume`). */
      activeRunStore.set(runId);
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const run = await runsGateway.getRun(runId);
          if (generationRef.current !== generation) return;
          if (applyRun(run) && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch (err) {
          if (generationRef.current !== generation) return;
          if (isRunGone(err)) {
            void expireRun(runId, generation, liveUrlRef.current);
            return;
          }
          /* The interval stops, and the screen stops claiming progress:
             `HomeScreen` reads (error && status is queued or processing) as
             "connection lost". What changed is that this is no longer the end —
             a reconnect is scheduled and counted down on screen, and a good
             response puts the pipeline straight back. */
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          fail(err, POLL_FALLBACK);
          setLostCause(lostCauseOf(err));
          scheduleReconnectRef.current(generation);
        }
      }, POLL_INTERVAL_MS);
    },
    [applyRun, expireRun, fail]
  );

  const attemptReconnect = useCallback(
    async (generation: number) => {
      const runId = runIdRef.current;
      if (!runId || generationRef.current !== generation) return;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (tickRef.current) clearInterval(tickRef.current);
      reconnectTimerRef.current = null;
      tickRef.current = null;
      setReconnectIn(null);
      setReconnecting(true);
      try {
        const run = await runsGateway.getRun(runId);
        if (generationRef.current !== generation) return;
        setError(null);
        clearReconnect();
        if (!applyRun(run)) startPolling(runId, generation);
      } catch (err) {
        if (generationRef.current !== generation) return;
        if (isRunGone(err)) {
          void expireRun(runId, generation, liveUrlRef.current);
          return;
        }
        fail(err, POLL_FALLBACK);
        setLostCause(lostCauseOf(err));
        attemptRef.current += 1;
        scheduleReconnectRef.current(generation);
      }
    },
    [applyRun, clearReconnect, expireRun, fail, startPolling]
  );

  const scheduleReconnect = useCallback(
    (generation: number) => {
      const delay = reconnectDelay(attemptRef.current);
      const due = Date.now() + delay * 1000;
      setReconnecting(false);
      setReconnectIn(delay);
      setReconnectAttempt(attemptRef.current + 1);
      if (tickRef.current) clearInterval(tickRef.current);
      /* A wall-clock deadline rather than a decrementing counter, so a
         throttled background tab shows the true time left when it comes back
         instead of a number that froze while it was hidden. */
      tickRef.current = setInterval(() => {
        setReconnectIn(Math.max(0, Math.ceil((due - Date.now()) / 1000)));
      }, 1000);
      reconnectTimerRef.current = setTimeout(() => {
        void attemptReconnect(generation);
      }, delay * 1000);
    },
    [attemptReconnect]
  );

  useEffect(() => {
    scheduleReconnectRef.current = scheduleReconnect;
  }, [scheduleReconnect]);

  /* "Retry now": skip the rest of the countdown. A no-op unless a reconnect is
     actually pending, so a double press cannot put two requests on the wire. */
  const reconnectNow = useCallback(() => {
    if (!reconnectTimerRef.current) return;
    void attemptReconnect(generationRef.current);
  }, [attemptReconnect]);

  /* Why this does NOT optimistically set `status: "queued"` before awaiting.
     That transition unmounts the idle branch, and with it `UploadForm`'s local
     `url` state; a rejected request then returned to idle and the field
     remounted empty, so "try again" meant "retype the URL". The status now
     changes exactly once, when the server has actually accepted the run — which
     is also the only point at which "queued" is true. `submitting` is what
     carries the intervening moment: it keeps the form mounted (input intact),
     disables its controls so there is no double-submit window, and gives the
     button a busy label so a successful submit still responds instantly. For a
     file upload the wait is the upload itself, which the old optimistic
     pipeline mislabelled as "normalizing" while the bytes were still leaving
     the browser. */
  const submit = useCallback(
    async (source: MediaSource) => {
      if (submittingRef.current) return;
      submittingRef.current = true;
      setSubmitting(true);
      stopTimers();
      clearReconnect();
      activeRunStore.clear();
      setError(null);
      setExpired(null);
      setResult(null);
      setCompleteness("full");
      setSourceMetadata(null);
      setDurationSeconds(null);
      setStage(null);
      setSourceKind(source.url ? "url" : "file");
      setMediaKind(mediaKindOfSource(source));
      setFreeRunRefunded(false);
      /* Taken before the request, so it is the count this run would spend
         from. Unknown (null) means no refund line can ever be claimed. */
      freeRunsBeforeRef.current = usingOwnKey() ? null : currentFreeRuns();
      const generation = ++generationRef.current;
      try {
        let run;
        try {
          run = await runsGateway.createRun(source);
        } catch (err) {
          /* Free runs (Phase 5b): the stored device token was missing or no
             longer valid. Read the allowance again — the adapter stores the
             fresh token the server issues — and send the same run once more.
             Once only: a second refusal is reported like any other. */
          if (!(err instanceof ApiError && err.code === "device_token_invalid")) throw err;
          await refreshFreeRuns();
          if (generationRef.current !== generation) return;
          run = await runsGateway.createRun(source);
        }
        /* Filed even if the screen has moved on: the run exists server-side
           and belongs in History either way. */
        recordSubmitted(run.run_id, run.status, source);
        noteRunAccepted();
        if (generationRef.current !== generation) return;
        setSourceName(describeSource(source));
        setRetrySource(source);
        liveUrlRef.current = source.url || null;
        setStatus(run.status);
        startPolling(run.run_id, generation);
      } catch (err) {
        /* Out of free runs. Marked even if the screen moved on, and even when
           the cached count still said runs were left — the 402 is the newer
           truth. No error line: the limit banner above the card says it, with
           the one action that fixes it, and the form stays as typed. */
        if (err instanceof ApiError && err.code === "free_runs_used") {
          markFreeRunsUsed(err.limit, err.used, err.scope);
          if (generationRef.current !== generation) return;
          /* A retry from the failed view lands here too; the banner lives on
             the intake, so go back to it. With a key saved the banner is
             hidden, so the server's own sentence is the only explanation. */
          setStatus("idle");
          if (apiKeyStore.get()) fail(err, SUBMIT_FALLBACK);
          return;
        }
        if (generationRef.current !== generation) return;
        fail(err, SUBMIT_FALLBACK);
      } finally {
        submittingRef.current = false;
        setSubmitting(false);
      }
    },
    [clearReconnect, fail, startPolling, stopTimers]
  );

  const reset = useCallback(() => {
    /* Stop every timer first. The poll is `setStatus(run.status)` on a timer
       and a pending reconnect would revive it, so leaving either running meant
       "analyze another file" bounced straight back to the pipeline. */
    stopTimers();
    clearReconnect();
    activeRunStore.clear();
    runIdRef.current = null;
    liveUrlRef.current = null;
    generationRef.current += 1;
    freeRunsBeforeRef.current = null;
    setStatus("idle");
    setStage(null);
    setSourceKind("file");
    setMediaKind(null);
    setFreeRunRefunded(false);
    setResult(null);
    setCompleteness("full");
    setSourceMetadata(null);
    setSourceName(null);
    setDurationSeconds(null);
    setRetrySource(null);
    setError(null);
    setExpired(null);
  }, [clearReconnect, stopTimers]);

  /* `sourceKindHint` is the History summary's `source_kind`, when it has one,
     so a reopened run shows the right frames before its first status
     response lands. Absent (legacy rows), the run starts as "file" and
     `applyRun` corrects it.

     `resumed` (refinement 6, RUN-06 web): this is the run this tab was
     watching before a reload. The tab itself knows the run, so a 404 is
     "expired" even without a History record (IndexedDB may be blocked), and
     a failed read is a lost connection to reconnect from, not a reason to
     drop back to the intake. */
  const openRun = useCallback(
    async (runId: string, sourceKindHint?: RunSourceKind | null, { resumed = false }: { resumed?: boolean } = {}) => {
      stopTimers();
      clearReconnect();
      if (!resumed) activeRunStore.clear();
      setError(null);
      setResult(null);
      setCompleteness("full");
      setSourceMetadata(null);
      setSourceName(null);
      setDurationSeconds(null);
      setRetrySource(null);
      setExpired(null);
      liveUrlRef.current = null;
      freeRunsBeforeRef.current = null;
      setFreeRunRefunded(false);
      setMediaKind(null);
      setSourceKind(sourceKindHint === "link" ? "url" : "file");
      setStatus("processing");
      const generation = ++generationRef.current;
      /* Whether this browser has its own record of the run. A 404 for one it
         knows means "expired"; for an id it has never seen it just means
         "not found" (refinement 3, #1). */
      let known = resumed;
      let knownUrl: string | null = null;
      /* History first: a finished run reopens from this browser with no
         network at all. Only a record without a result (still running, or
         one the store could not hold) falls through to the server. */
      try {
        const record = await historyStore.get(runId);
        if (generationRef.current !== generation) return;
        if (record) {
          known = true;
          knownUrl = record.source_url ?? record.source_metadata?.source_url ?? null;
          if (record.source_kind) setSourceKind(record.source_kind === "link" ? "url" : "file");
          const recordKind = mediaKindOfPlatform(record.platform);
          if (recordKind) setMediaKind(recordKind);
        }
        /* A resumed link run gets back what the live run had: its link on
           the source chip, "Analyze it again" if it expires, and "Try again"
           if it fails. */
        if (resumed && knownUrl) {
          liveUrlRef.current = knownUrl;
          setSourceName(describeSource({ url: knownUrl }));
          setRetrySource({ url: knownUrl });
        }
        /* What this browser remembers about an upload: its name (never sent
           to or kept by the server) and its length. */
        if (record?.file_name) setSourceName(record.file_name);
        if (typeof record?.duration_seconds === "number") setDurationSeconds(record.duration_seconds);
        if (record && ((record.status === "complete" && record.result) || record.status === "failed")) {
          /* Settled while nobody was watching: nothing left to resume. */
          if (resumed) activeRunStore.clear();
          setSourceKind(record.source_kind === "link" ? "url" : "file");
          if (record.source_metadata) setSourceMetadata(record.source_metadata);
          setStatus(record.status);
          setStage(null);
          if (record.status === "complete") {
            setResult(record.result);
            setCompleteness(record.completeness ?? "full");
          } else {
            setError(record.error || "The analysis failed.");
            if (record.error === EXPIRED_MESSAGE) {
              setExpired({
                againUrl: record.source_url ?? record.source_metadata?.source_url ?? null,
              });
            }
          }
          return;
        }
      } catch {
        /* no usable History here — ask the server as before */
      }
      if (generationRef.current !== generation) return;
      try {
        const run = await runsGateway.getRun(runId);
        if (generationRef.current !== generation) return;
        if (!applyRun(run)) startPolling(runId, generation);
      } catch (err) {
        if (generationRef.current !== generation) return;
        if (known && isRunGone(err)) {
          runIdRef.current = runId;
          void expireRun(runId, generation, knownUrl);
          return;
        }
        if (resumed) {
          /* The run may well still be going; this tab just could not ask.
             The connection-lost screen, counting down to the next try. */
          runIdRef.current = runId;
          fail(err, POLL_FALLBACK);
          setLostCause(lostCauseOf(err));
          scheduleReconnectRef.current(generation);
          return;
        }
        setStatus("idle");
        fail(err, OPEN_FALLBACK);
      }
    },
    [applyRun, clearReconnect, expireRun, fail, startPolling, stopTimers]
  );

  /* Refinement 6 (RUN-06 web): on a load of the app, pick up the run this tab
     was watching when it was reloaded, and show it (progress, result, failed
     or expired) instead of a fresh intake. Only when the load carries no
     other intent: a link shared in takes the intake, and an address naming
     another tab (`?view=history`) opens that tab. Returns whether it resumed. */
  const resume = useCallback((): boolean => {
    if (typeof window === "undefined") return false;
    const view = new URLSearchParams(window.location.search).get("view");
    if (view && view !== "analyze") return false;
    if (sharedUrlSource.pending()) return false;
    const runId = activeRunStore.get();
    if (!runId) return false;
    void openRun(runId, null, { resumed: true });
    return true;
  }, [openRun]);

  /* Resubmit the run that just failed, same link or same file. Only offered
     while `canRetry` is true. */
  const retry = useCallback(() => {
    if (retrySource) void submit(retrySource);
  }, [retrySource, submit]);

  return {
    status,
    stage,
    sourceKind,
    mediaKind,
    freeRunRefunded,
    result,
    completeness,
    sourceMetadata,
    error,
    submitting,
    sourceName,
    durationSeconds,
    canRetry: retrySource !== null,
    expired: expired !== null,
    againUrl: expired?.againUrl ?? null,
    reconnectIn,
    reconnecting,
    reconnectAttempt,
    lostCause,
    submit,
    retry,
    reconnectNow,
    reset,
    openRun,
    resume,
  };
}
