"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link2, UploadCloud } from "lucide-react";
import type { MediaSource } from "@/domain/entities";

const ACCEPTED_EXTENSIONS = [".mp3", ".mp4", ".mov"];
const MAX_FILE_SIZE_MB = 200;
const MAX_DURATION_SECONDS = 180;
const MEDIA_TERMS_ACCEPTANCE_KEY = "videolens-media-terms-v1";

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
  const [url, setUrl] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [checking, setChecking] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setAcceptedTerms(
      window.localStorage.getItem(MEDIA_TERMS_ACCEPTANCE_KEY) === "accepted"
    );

    const consumeSharedUrl = () => {
      const params = new URLSearchParams(window.location.search);
      const nativeText = window.localStorage.getItem("videolens-shared-text") || "";
      const shared =
        params.get("url") ||
        params.get("text")?.match(/https?:\/\/\S+/)?.[0] ||
        nativeText.match(/https?:\/\/\S+/)?.[0];
      if (shared) {
        setUrl(shared);
        window.localStorage.removeItem("videolens-shared-text");
      }
    };

    consumeSharedUrl();
    window.addEventListener("videolens-share", consumeSharedUrl);
    return () => window.removeEventListener("videolens-share", consumeSharedUrl);
  }, []);

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
        // Backend performs authoritative validation
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
    if (!acceptedTerms) {
      setError("Accept the media-use terms before analysis.");
      return;
    }
    const validationError = validateUrl(value);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    onSubmit({ url: value });
  };

  return (
    <section className="flex flex-col gap-4" aria-disabled={disabled || undefined}>
      {/* 1. PRIMARY: Paste Public Video URL (Top Focus) */}
      <form onSubmit={submitUrl} className="flex flex-col gap-2.5">
        <label htmlFor="media-url" className="flex items-center gap-2 text-sm font-bold text-[var(--color-text-strong)]">
          <Link2 className="h-4 w-4 text-[var(--color-accent)]" />
          <span>Paste Video or Audio URL (Primary)</span>
        </label>
        <div className="flex flex-col gap-2.5 sm:flex-row">
          <input
            id="media-url"
            type="url"
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
              setError(null);
            }}
            placeholder="https://www.instagram.com/reel/..., YouTube, TikTok, or public video link"
            autoComplete="url"
            disabled={disabled}
            aria-invalid={Boolean(error)}
            className="field min-w-0 flex-1 text-sm font-medium"
          />
          <button
            type="submit"
            disabled={disabled || !url.trim() || !acceptedTerms}
            className="button-primary text-xs font-bold px-6 py-2.5 sm:shrink-0 shadow-lg shadow-indigo-950/40"
          >
            Analyze URL
          </button>
        </div>
      </form>

      {/* 2. OR Divider */}
      <div className="relative flex items-center justify-center my-1">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-[var(--color-rule)]" />
        </div>
        <span className="relative bg-[var(--color-surface)] px-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-muted)] rounded-full border border-[var(--color-rule)]">
          or upload a local file (secondary)
        </span>
      </div>

      {/* 3. SECONDARY: File Drag & Drop Zone (Bottom Focus) */}
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
          if (!acceptedTerms) {
            setError("Accept the media-use terms before analysis.");
          } else if (file) {
            void handleFile(file);
          }
        }}
        className={`flex flex-col items-center justify-center gap-2 rounded-[var(--radius-lg)] border border-dashed px-4 py-5 text-center backdrop-blur-md transition-all ${
          dragActive
            ? "border-[var(--color-accent-hover)] bg-[var(--color-accent-soft)]"
            : "border-[var(--color-rule-strong)] bg-[var(--color-paper-2)]/60 hover:border-[var(--color-rule)]"
        }`}
      >
        <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-muted)]">
          <UploadCloud className="h-4 w-4 text-[var(--color-faint)]" />
          <span>Drop an audio or video file here or</span>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={disabled || checking || !acceptedTerms}
            aria-busy={checking}
            className="button-secondary text-xs px-3.5 py-1.5 font-semibold"
          >
            {checking ? "Checking..." : "Browse file"}
          </button>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".mp3,.mp4,.mov,audio/mpeg,video/mp4,video/quicktime"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (!acceptedTerms) {
              setError("Accept the media-use terms before analysis.");
            } else if (file) {
              void handleFile(file);
            }
            event.target.value = "";
          }}
        />
        <p className="text-[11px] text-[var(--color-faint)]">
          Supports MP3, MP4, or MOV up to {MAX_FILE_SIZE_MB}MB & 3 mins
        </p>
      </div>

      {/* 4. Terms Agreement Checkbox */}
      <label className="flex items-start gap-2.5 text-xs text-[var(--color-muted)] mt-0.5">
        <input
          type="checkbox"
          checked={acceptedTerms}
          disabled={disabled}
          onChange={(event) => {
            const accepted = event.target.checked;
            setAcceptedTerms(accepted);
            if (accepted) {
              window.localStorage.setItem(MEDIA_TERMS_ACCEPTANCE_KEY, "accepted");
            } else {
              window.localStorage.removeItem(MEDIA_TERMS_ACCEPTANCE_KEY);
            }
            setError(null);
          }}
          className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--color-accent)]"
        />
        <span>
          I will only submit media I own or am authorized to process, and I agree to the{" "}
          <a className="font-medium text-[var(--color-accent-hover)] underline underline-offset-2" href="/terms">
            Terms
          </a>{" "}
          and{" "}
          <a className="font-medium text-[var(--color-accent-hover)] underline underline-offset-2" href="/privacy">
            Privacy Policy
          </a>
          .
        </span>
      </label>

      {error && (
        <p role="alert" className="text-xs leading-5 text-[var(--color-danger)]">
          {error}
        </p>
      )}
    </section>
  );
}
