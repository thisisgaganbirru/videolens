"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AnalysisCompleteness,
  MediaSource,
  RunStatus,
  RunSourceKind,
  RunStatusResponse,
  SourceMetadata,
  VideoAnalysis,
} from "@/domain/entities";
import { classifyGatewayError } from "@/application/gatewayError";
import { recordRunResponse, recordSubmitted } from "@/application/historySync";
import { markFreeRunsUsed, noteRunAccepted, refreshFreeRuns } from "@/application/useFreeRuns";
import { ApiError } from "@/domain/errors";
import { apiKeyStore, historyStore, runsGateway } from "@/infrastructure/container";

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

export function useAnalysisRun() {
  const [status, setStatus] = useState<RunStatus | "idle">("idle");
  const [stage, setStage] = useState<string | null>(null);
  const [sourceKind, setSourceKind] = useState<"file" | "url">("file");
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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const runIdRef = useRef<string | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const attemptRef = useRef(0);
  /* Mirrors `submitting` for the guard below. State is read from a stale
     closure inside the same tick a second submit could arrive in; a ref is
     read at call time, which is what a re-entrancy guard needs. */
  const submittingRef = useRef(false);
  /* Bumped by every intent that replaces what is on screen — `submit`,
     `openRun`, `reset`. A request that was already in flight when the next
     intent arrived resolves into a screen that has moved on, so each one drops
     its result if the counter no longer matches the value it captured. Without
     it, a link shared mid-submit is undone a moment later by the 202 for the
     run the user just abandoned. The reconnect timers check it too. */
  const generationRef = useRef(0);

  /* Every timer this hook owns, stopped in one place: unmount, reset, openRun,
     a fresh submit and a successful reconnect all need exactly this. */
  const stopTimers = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    if (tickRef.current) clearInterval(tickRef.current);
    pollRef.current = null;
    reconnectTimerRef.current = null;
    tickRef.current = null;
  }, []);

  useEffect(() => stopTimers, [stopTimers]);

  const clearReconnect = useCallback(() => {
    attemptRef.current = 0;
    setReconnectIn(null);
    setReconnecting(false);
    setReconnectAttempt(0);
  }, []);

  const fail = useCallback((err: unknown, fallback: string) => {
    setError(classifyGatewayError(err, fallback).message);
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
    if (run.source_metadata) setSourceMetadata(run.source_metadata);
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
      setResult(run.result);
      setCompleteness(run.completeness ?? "full");
      return true;
    }
    if (run.status === "failed") {
      setError(run.error || "Video analysis failed.");
      return true;
    }
    return false;
  }, []);

  /* `startPolling` and `scheduleReconnect` reach each other (a dead poll
     schedules a reconnect; a good reconnect resumes polling), so the second is
     called through a ref rather than a dependency cycle. */
  const scheduleReconnectRef = useRef<(generation: number) => void>(() => {});

  const startPolling = useCallback(
    (runId: string, generation: number) => {
      runIdRef.current = runId;
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
          /* The interval stops, and the screen stops claiming progress:
             `HomeScreen` reads (error && status is queued or processing) as
             "connection lost". What changed is that this is no longer the end —
             a reconnect is scheduled and counted down on screen, and a good
             response puts the pipeline straight back. */
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          fail(err, POLL_FALLBACK);
          scheduleReconnectRef.current(generation);
        }
      }, POLL_INTERVAL_MS);
    },
    [applyRun, fail]
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
        fail(err, POLL_FALLBACK);
        attemptRef.current += 1;
        scheduleReconnectRef.current(generation);
      }
    },
    [applyRun, clearReconnect, fail, startPolling]
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
      setError(null);
      setResult(null);
      setCompleteness("full");
      setSourceMetadata(null);
      setStage(null);
      setSourceKind(source.url ? "url" : "file");
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
        setStatus(run.status);
        startPolling(run.run_id, generation);
      } catch (err) {
        /* Out of free runs. Marked even if the screen moved on, and even when
           the cached count still said runs were left — the 402 is the newer
           truth. No error line: the limit banner above the card says it, with
           the one action that fixes it, and the form stays as typed. */
        if (err instanceof ApiError && err.code === "free_runs_used") {
          markFreeRunsUsed(err.limit, err.used);
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
    runIdRef.current = null;
    generationRef.current += 1;
    setStatus("idle");
    setStage(null);
    setSourceKind("file");
    setResult(null);
    setCompleteness("full");
    setSourceMetadata(null);
    setSourceName(null);
    setRetrySource(null);
    setError(null);
  }, [clearReconnect, stopTimers]);

  /* `sourceKindHint` is the History summary's `source_kind`, when it has one,
     so a reopened run shows the right frames before its first status
     response lands. Absent (legacy rows), the run starts as "file" and
     `applyRun` corrects it. */
  const openRun = useCallback(
    async (runId: string, sourceKindHint?: RunSourceKind | null) => {
      stopTimers();
      clearReconnect();
      setError(null);
      setResult(null);
      setCompleteness("full");
      setSourceMetadata(null);
      setSourceName(null);
      setRetrySource(null);
      setSourceKind(sourceKindHint === "link" ? "url" : "file");
      setStatus("processing");
      const generation = ++generationRef.current;
      /* History first: a finished run reopens from this browser with no
         network at all. Only a record without a result (still running, or
         one the store could not hold) falls through to the server. */
      try {
        const record = await historyStore.get(runId);
        if (generationRef.current !== generation) return;
        if (record && ((record.status === "complete" && record.result) || record.status === "failed")) {
          setSourceKind(record.source_kind === "link" ? "url" : "file");
          if (record.source_metadata) setSourceMetadata(record.source_metadata);
          setStatus(record.status);
          setStage(null);
          if (record.status === "complete") {
            setResult(record.result);
            setCompleteness(record.completeness ?? "full");
          } else {
            setError(record.error || "Video analysis failed.");
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
        setStatus("idle");
        fail(err, OPEN_FALLBACK);
      }
    },
    [applyRun, clearReconnect, fail, startPolling, stopTimers]
  );

  /* Resubmit the run that just failed, same link or same file. Only offered
     while `canRetry` is true. */
  const retry = useCallback(() => {
    if (retrySource) void submit(retrySource);
  }, [retrySource, submit]);

  return {
    status,
    stage,
    sourceKind,
    result,
    completeness,
    sourceMetadata,
    error,
    submitting,
    sourceName,
    canRetry: retrySource !== null,
    reconnectIn,
    reconnecting,
    reconnectAttempt,
    submit,
    retry,
    reconnectNow,
    reset,
    openRun,
  };
}
