"use client";

import { FormEvent, useCallback, useRef, useState } from "react";
import type { MediaSource } from "@/lib/api";

const ACCEPTED_EXTENSIONS = [".mp3", ".mp4", ".mov"];
const MAX_FILE_SIZE_MB = 200;
const MAX_DURATION_SECONDS = 180;

interface UploadFormProps {
  onSubmit: (source: MediaSource) => void;
  disabled?: boolean;
}

function validateFile(file: File): string | null {
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!ACCEPTED_EXTENSIONS.includes(ext)) {
    return "Only MP3, MP4, and MOV files are supported.";
  }
  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    return `File is larger than the ${MAX_FILE_SIZE_MB}MB limit.`;
  }
  return null;
}

function validateUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error();
    return null;
  } catch {
    return "Enter a valid public HTTP or HTTPS URL.";
  }
}

function readMediaDuration(file: File): Promise<number> {
  return new Promise((resolve, reject) => {
    const media = document.createElement(file.name.toLowerCase().endsWith(".mp3") ? "audio" : "video");
    media.preload = "metadata";
    media.onloadedmetadata = () => {
      URL.revokeObjectURL(media.src);
      resolve(media.duration);
    };
    media.onerror = () => {
      URL.revokeObjectURL(media.src);
      reject(new Error("Could not read media metadata."));
    };
    media.src = URL.createObjectURL(file);
  });
}

export default function UploadForm({ onSubmit, disabled }: UploadFormProps) {
  const [mode, setMode] = useState<"file" | "url">("file");
  const [url, setUrl] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    async (file: File) => {
      const validationError = validateFile(file);
      if (validationError) {
        setError(validationError);
        return;
      }

      setError(null);
      setChecking(true);
      try {
        const duration = await readMediaDuration(file);
        if (duration > MAX_DURATION_SECONDS) {
          setError(
            `Media is ${Math.round(duration)}s long, which exceeds the ${MAX_DURATION_SECONDS}s limit.`
          );
          return;
        }
      } catch {
        // The backend performs the authoritative media validation.
      } finally {
        setChecking(false);
      }

      onSubmit({ file });
    },
    [onSubmit]
  );

  const submitUrl = (event: FormEvent) => {
    event.preventDefault();
    const value = url.trim();
    const validationError = validateUrl(value);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    onSubmit({ url: value });
  };

  const selectMode = (nextMode: "file" | "url") => {
    setMode(nextMode);
    setError(null);
  };

  return (
    <section className={`flex flex-col gap-4 ${disabled ? "pointer-events-none opacity-50" : ""}`}>
      <div className="grid grid-cols-2 border-b border-slate-800" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "file"}
          onClick={() => selectMode("file")}
          className={`border-b-2 px-4 py-3 text-sm font-medium ${
            mode === "file"
              ? "border-indigo-400 text-slate-100"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          Upload file
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "url"}
          onClick={() => selectMode("url")}
          className={`border-b-2 px-4 py-3 text-sm font-medium ${
            mode === "url"
              ? "border-indigo-400 text-slate-100"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          Paste URL
        </button>
      </div>

      {mode === "file" ? (
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragActive(false);
            const file = event.dataTransfer.files?.[0];
            if (file) void handleFile(file);
          }}
          className={`flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-12 text-center transition-colors ${
            dragActive ? "border-indigo-400 bg-indigo-950/30" : "border-slate-700"
          }`}
        >
          <p className="text-lg font-medium">Drop an audio or video file here</p>
          <p className="text-sm text-slate-400">or</p>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={checking}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
          >
            {checking ? "Checking media..." : "Choose a file"}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept=".mp3,.mp4,.mov,audio/mpeg,video/mp4,video/quicktime"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void handleFile(file);
              event.target.value = "";
            }}
          />
          <p className="text-xs text-slate-500">
            MP3, MP4, or MOV, up to {MAX_FILE_SIZE_MB}MB and 3 minutes long.
          </p>
        </div>
      ) : (
        <form onSubmit={submitUrl} className="flex flex-col gap-3 py-4">
          <label htmlFor="media-url" className="text-sm font-medium text-slate-200">
            Public media URL
          </label>
          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              id="media-url"
              type="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://www.instagram.com/reel/..."
              autoComplete="url"
              className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none placeholder:text-slate-600 focus:border-indigo-400"
            />
            <button
              type="submit"
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500"
            >
              Download and analyze
            </button>
          </div>
          <p className="text-xs text-slate-500">
            Supports public links from sites handled by the downloader. Private or login-only posts may fail.
          </p>
        </form>
      )}

      {error && <p className="text-sm text-red-400">{error}</p>}
    </section>
  );
}
