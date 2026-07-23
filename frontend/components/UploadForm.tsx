"use client";

import { useCallback, useRef, useState } from "react";

const ACCEPTED_EXTENSIONS = [".mp4", ".mov"];
const MAX_FILE_SIZE_MB = 200;
const MAX_DURATION_SECONDS = 180;

interface UploadFormProps {
  onSubmit: (file: File) => void;
  disabled?: boolean;
}

function validate(file: File): string | null {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!ACCEPTED_EXTENSIONS.includes(ext)) {
    return "Only .mp4 and .mov files are supported.";
  }
  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    return `File is larger than the ${MAX_FILE_SIZE_MB}MB limit.`;
  }
  return null;
}

function readVideoDuration(file: File): Promise<number> {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    video.preload = "metadata";
    video.onloadedmetadata = () => {
      URL.revokeObjectURL(video.src);
      resolve(video.duration);
    };
    video.onerror = () => {
      URL.revokeObjectURL(video.src);
      reject(new Error("Could not read video metadata."));
    };
    video.src = URL.createObjectURL(file);
  });
}

export default function UploadForm({ onSubmit, disabled }: UploadFormProps) {
  const [dragActive, setDragActive] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    async (file: File) => {
      const validationError = validate(file);
      if (validationError) {
        setError(validationError);
        return;
      }

      setError(null);
      setChecking(true);
      try {
        const duration = await readVideoDuration(file);
        if (duration > MAX_DURATION_SECONDS) {
          setError(
            `Video is ${Math.round(duration)}s long, which exceeds the ${MAX_DURATION_SECONDS}s limit.`
          );
          return;
        }
      } catch {
        // Some containers don't expose duration via the browser; let the backend validate it.
      } finally {
        setChecking(false);
      }

      onSubmit(file);
    },
    [onSubmit]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragActive(false);
        const file = e.dataTransfer.files?.[0];
        if (file) void handleFile(file);
      }}
      className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-12 text-center transition-colors ${
        dragActive ? "border-indigo-400 bg-indigo-950/30" : "border-slate-700"
      } ${disabled ? "pointer-events-none opacity-50" : ""}`}
    >
      <p className="text-lg font-medium">Drop a video here</p>
      <p className="text-sm text-slate-400">or</p>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={checking}
        className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
      >
        {checking ? "Checking video..." : "Choose a file"}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".mp4,.mov,video/mp4,video/quicktime"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleFile(file);
          e.target.value = "";
        }}
      />
      <p className="text-xs text-slate-500">
        MP4 or MOV, up to {MAX_FILE_SIZE_MB}MB and 3 minutes long.
      </p>
      {error && <p className="text-sm text-red-400">{error}</p>}
    </div>
  );
}
