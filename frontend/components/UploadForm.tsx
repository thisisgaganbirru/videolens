"use client";

import { useCallback, useRef, useState } from "react";

const ACCEPTED_EXTENSIONS = [".mp4", ".mov"];
const MAX_FILE_SIZE_MB = 200;

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

export default function UploadForm({ onSubmit, disabled }: UploadFormProps) {
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File) => {
      const validationError = validate(file);
      if (validationError) {
        setError(validationError);
        return;
      }
      setError(null);
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
        if (file) handleFile(file);
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
        className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500"
      >
        Choose a file
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".mp4,.mov,video/mp4,video/quicktime"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
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
