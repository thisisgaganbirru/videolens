"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AnalysisCompleteness,
  MediaSource,
  RunStatus,
  SourceMetadata,
  VideoAnalysis,
} from "@/domain/entities";
import { classifyGatewayError, type GatewayErrorKind } from "@/application/gatewayError";
import { runsGateway } from "@/infrastructure/container";

const POLL_INTERVAL_MS = 3000;

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
  /* null when the error came from the run itself (a `failed` status carries the
     backend's own reason, which is not a transport classification at all). */
  const [errorKind, setErrorKind] = useState<GatewayErrorKind | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  /* Mirrors `submitting` for the guard below. State is read from a stale
     closure inside the same tick a second submit could arrive in; a ref is
     read at call time, which is what a re-entrancy guard needs. */
  const submittingRef = useRef(false);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const fail = useCallback((err: unknown, fallback: string) => {
    const failure = classifyGatewayError(err, fallback);
    setError(failure.message);
    setErrorKind(failure.kind);
  }, []);

  const pollRun = useCallback(
    (runId: string) => {
      pollRef.current = setInterval(async () => {
        try {
          const run = await runsGateway.getRun(runId);
          setStatus(run.status);
          setStage(run.stage);
          if (run.source_metadata) setSourceMetadata(run.source_metadata);
          if (run.status === "complete") {
            setResult(run.result);
            setCompleteness(run.completeness ?? "full");
            if (pollRef.current) clearInterval(pollRef.current);
          } else if (run.status === "failed") {
            setError(run.error || "Video analysis failed.");
            setErrorKind(null);
            if (pollRef.current) clearInterval(pollRef.current);
          }
        } catch (err) {
          /* The interval dies here, so the pipeline on screen is frozen from
             this moment on. `HomeScreen` reads (error && status is queued or
             processing) as exactly that condition and tells `RunStatusView` to
             stop claiming progress. */
          fail(err, POLL_FALLBACK);
          if (pollRef.current) clearInterval(pollRef.current);
        }
      }, POLL_INTERVAL_MS);
    },
    [fail]
  );

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
      setError(null);
      setErrorKind(null);
      setResult(null);
      setCompleteness("full");
      setSourceMetadata(null);
      setStage(null);
      setSourceKind(source.url ? "url" : "file");
      try {
        const run = await runsGateway.createRun(source);
        setStatus(run.status);
        pollRun(run.run_id);
      } catch (err) {
        fail(err, SUBMIT_FALLBACK);
      } finally {
        submittingRef.current = false;
        setSubmitting(false);
      }
    },
    [fail, pollRun]
  );

  const reset = useCallback(() => {
    setStatus("idle");
    setStage(null);
    setSourceKind("file");
    setResult(null);
    setCompleteness("full");
    setSourceMetadata(null);
    setError(null);
    setErrorKind(null);
  }, []);

  const openRun = useCallback(
    async (runId: string) => {
      if (pollRef.current) clearInterval(pollRef.current);
      setError(null);
      setErrorKind(null);
      setResult(null);
      setCompleteness("full");
      setSourceMetadata(null);
      setSourceKind("file");
      setStatus("processing");
      try {
        const run = await runsGateway.getRun(runId);
        setStatus(run.status);
        setStage(run.stage);
        if (run.source_metadata) setSourceMetadata(run.source_metadata);
        if (run.status === "complete") {
          setResult(run.result);
          setCompleteness(run.completeness ?? "full");
        } else if (run.status === "failed") {
          setError(run.error || "Video analysis failed.");
          setErrorKind(null);
        } else {
          pollRun(runId);
        }
      } catch (err) {
        setStatus("idle");
        fail(err, OPEN_FALLBACK);
      }
    },
    [fail, pollRun]
  );

  return {
    status,
    stage,
    sourceKind,
    result,
    completeness,
    sourceMetadata,
    error,
    errorKind,
    submitting,
    submit,
    reset,
    openRun,
  };
}
