"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import UploadForm from "@/components/UploadForm";
import RunStatusView from "@/components/RunStatusView";
import ResultsView from "@/components/ResultsView";
import { ApiError, createRun, getRun, type MediaSource } from "@/lib/api";
import type { RunStatus, VideoAnalysis } from "@/lib/types";

const POLL_INTERVAL_MS = 3000;

export default function Home() {
  const [status, setStatus] = useState<RunStatus | "idle">("idle");
  const [stage, setStage] = useState<string | null>(null);
  const [sourceKind, setSourceKind] = useState<"file" | "url">("file");
  const [result, setResult] = useState<VideoAnalysis | null>(null);
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
        const run = await getRun(runId);
        setStatus(run.status);
        setStage(run.stage);
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

  const handleSubmit = useCallback(
    async (source: MediaSource) => {
      setError(null);
      setResult(null);
      setStage(null);
      setSourceKind(source.url ? "url" : "file");
      setStatus("queued");
      try {
        const run = await createRun(source);
        setStatus(run.status);
        pollRun(run.run_id);
      } catch (err) {
        setStatus("idle");
        setError(err instanceof ApiError ? err.message : "Could not submit media.");
      }
    },
    [pollRun]
  );

  const reset = () => {
    setStatus("idle");
    setStage(null);
    setSourceKind("file");
    setResult(null);
    setError(null);
  };

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-16">
      <div>
        <h1 className="text-2xl font-semibold">VideoLens AI</h1>
        <p className="text-sm text-slate-400">
          Upload media or paste a public link to get a transcript, summary, and notes.
        </p>
      </div>

      {status === "idle" && <UploadForm onSubmit={handleSubmit} />}

      {status !== "idle" && (
        <RunStatusView status={status} stage={stage} sourceKind={sourceKind} error={error} />
      )}

      {error && status !== "failed" && (
        <div className="rounded-xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {status === "complete" && result && <ResultsView result={result} />}

      {(status === "complete" || status === "failed" || error) && (
        <button
          type="button"
          onClick={reset}
          className="self-start text-sm text-indigo-300 hover:underline"
        >
          Analyze another file
        </button>
      )}
    </main>
  );
}
