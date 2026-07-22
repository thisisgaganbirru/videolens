"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import UploadForm from "@/components/UploadForm";
import JobStatusView from "@/components/JobStatusView";
import ResultsView from "@/components/ResultsView";
import { ApiError, createJob, getJob } from "@/lib/api";
import type { JobStatus, VideoAnalysis } from "@/lib/types";

const POLL_INTERVAL_MS = 3000;

export default function Home() {
  const [status, setStatus] = useState<JobStatus | "idle">("idle");
  const [result, setResult] = useState<VideoAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const pollJob = useCallback((jobId: string) => {
    pollRef.current = setInterval(async () => {
      try {
        const job = await getJob(jobId);
        setStatus(job.status);
        if (job.status === "complete") {
          setResult(job.result);
          if (pollRef.current) clearInterval(pollRef.current);
        } else if (job.status === "failed") {
          setError(job.error || "Video analysis failed.");
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong.");
        if (pollRef.current) clearInterval(pollRef.current);
      }
    }, POLL_INTERVAL_MS);
  }, []);

  const handleSubmit = useCallback(
    async (file: File) => {
      setError(null);
      setResult(null);
      setStatus("queued");
      try {
        const job = await createJob(file);
        setStatus(job.status);
        pollJob(job.job_id);
      } catch (err) {
        setStatus("idle");
        setError(err instanceof ApiError ? err.message : "Upload failed.");
      }
    },
    [pollJob]
  );

  const reset = () => {
    setStatus("idle");
    setResult(null);
    setError(null);
  };

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-16">
      <div>
        <h1 className="text-2xl font-semibold">VideoLens AI</h1>
        <p className="text-sm text-slate-400">
          Upload a short video and get a transcript, on-screen text, summary, and notes.
        </p>
      </div>

      {status === "idle" && <UploadForm onSubmit={handleSubmit} />}

      {(status === "queued" || status === "processing") && <JobStatusView status={status} />}

      {error && (
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
          Analyze another video
        </button>
      )}
    </main>
  );
}
