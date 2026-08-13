"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { MediaSource, RunStatus, SourceMetadata, VideoAnalysis } from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import { runsGateway } from "@/infrastructure/container";

const POLL_INTERVAL_MS = 3000;

export function useAnalysisRun() {
  const [status, setStatus] = useState<RunStatus | "idle">("idle");
  const [stage, setStage] = useState<string | null>(null);
  const [sourceKind, setSourceKind] = useState<"file" | "url">("file");
  const [result, setResult] = useState<VideoAnalysis | null>(null);
  const [sourceMetadata, setSourceMetadata] = useState<SourceMetadata | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const pollRun = useCallback((runId: string) => {
    pollRef.current = setInterval(async () => {
      try {
        const run = await runsGateway.getRun(runId);
        setStatus(run.status);
        setStage(run.stage);
        if (run.source_metadata) setSourceMetadata(run.source_metadata);
        if (run.status === "complete") {
          setResult(run.result);
          if (pollRef.current) clearInterval(pollRef.current);
        } else if (run.status === "failed") {
          setError(run.error || "Video analysis failed.");
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong.");
        if (pollRef.current) clearInterval(pollRef.current);
      }
    }, POLL_INTERVAL_MS);
  }, []);

  const submit = useCallback(
    async (source: MediaSource) => {
      setError(null);
      setResult(null);
      setSourceMetadata(null);
      setStage(null);
      setSourceKind(source.url ? "url" : "file");
      setStatus("queued");
      try {
        const run = await runsGateway.createRun(source);
        setStatus(run.status);
        pollRun(run.run_id);
      } catch (err) {
        setStatus("idle");
        setError(err instanceof ApiError ? err.message : "Could not submit media.");
      }
    },
    [pollRun]
  );

  const reset = useCallback(() => {
    setStatus("idle");
    setStage(null);
    setSourceKind("file");
    setResult(null);
    setSourceMetadata(null);
    setError(null);
  }, []);

  const openRun = useCallback(
    async (runId: string) => {
      if (pollRef.current) clearInterval(pollRef.current);
      setError(null);
      setResult(null);
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
        } else if (run.status === "failed") {
          setError(run.error || "Video analysis failed.");
        } else {
          pollRun(runId);
        }
      } catch (err) {
        setStatus("idle");
        setError(err instanceof ApiError ? err.message : "Could not load that run.");
      }
    },
    [pollRun]
  );

  return { status, stage, sourceKind, result, sourceMetadata, error, submit, reset, openRun };
}
