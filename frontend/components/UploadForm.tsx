"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import type { MediaSource } from "@/domain/entities";
import type { SharedUrl } from "@/application/useSharedUrl";

const ACCEPTED_EXTENSIONS = [".mp3", ".mp4", ".mov"];
const MAX_FILE_SIZE_MB = 200;
const MAX_DURATION_SECONDS = 180;
const MEDIA_TERMS_ACCEPTANCE_KEY = "videolens-media-terms-v1";

interface UploadFormProps {
  onSubmit: (source: MediaSource) => void;
  disabled?: boolean;
  /** The submit request is in flight. Distinct from `disabled` because it also
   *  relabels the primary button: the form now stays mounted for the whole
   *  request (so a rejection does not wipe the typed URL), which means it is
   *  the form that has to show the wait. */
  submitting?: boolean;
  /** The most recent link shared into the app, or null. A new object per
   *  arrival, so re-sharing the same link still fills the field. `HomeScreen`
   *  owns the listener and has already returned the shell to a fresh intake by
   *  the time this lands; all this component does is take the value. */
  sharedUrl?: SharedUrl | null;
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

export default function UploadForm({ onSubmit, disabled, submitting, sharedUrl }: UploadFormProps) {
  const busy = disabled || submitting;
  const [url, setUrl] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [checking, setChecking] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /* Which of the two entry points is waiting. Both are disabled while a submit
     is in flight, but only the one the user actually pressed should say so —
     "sending…" on both reads as two things happening at once. */
  const [pendingKind, setPendingKind] = useState<"url" | "file" | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!submitting) setPendingKind(null);
  }, [submitting]);

  useEffect(() => {
    setAcceptedTerms(
      window.localStorage.getItem(MEDIA_TERMS_ACCEPTANCE_KEY) === "accepted"
    );
  }, []);

  /* Runs on mount too, which is the case that matters: a share arriving over a
     finished result remounts this form (HomeScreen resets the run), and the
     link has to be waiting in the field when it comes back. */
  useEffect(() => {
    if (!sharedUrl) return;
    setUrl(sharedUrl.url);
    setError(null);
  }, [sharedUrl]);

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

      setPendingKind("file");
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
    setPendingKind("url");
    onSubmit({ url: value });
  };

  const rejectUnaccepted = () => {
    setError("Accept the media-use terms before analysis.");
  };

  /* No surface, no frame, no card: this control sits directly inside
     HomeScreen's `.intake` (which already renders the "new analysis"
     micro-label). Structure is the field's own edge, the rule of the
     divider, and the dashed drop zone — nothing wraps them. */
  return (
    <>
      <form onSubmit={submitUrl} className="row">
        <label htmlFor="media-url" className="sr-only">
          Video or audio URL
        </label>
        <input
          id="media-url"
          type="url"
          value={url}
          onChange={(event) => {
            setUrl(event.target.value);
            setError(null);
          }}
          placeholder="paste a youtube, tiktok, or instagram link"
          autoComplete="url"
          disabled={busy}
          aria-invalid={error ? "true" : undefined}
          aria-describedby={error ? "intake-error" : undefined}
          className="field"
        />
        <button
          type="submit"
          disabled={busy || !url.trim() || !acceptedTerms}
          aria-busy={pendingKind === "url" && submitting ? true : undefined}
          className="btn btn-primary"
        >
          {pendingKind === "url" && submitting ? "sending…" : "analyze url"}
        </button>
      </form>

      <div className="divider" aria-hidden="true">
        or
      </div>

      <div
        data-dragging={dragActive ? "true" : undefined}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          /* The drop zone has no disabled state of its own, so it is the one
             entry point that could still fire mid-submit. The hook guards
             against the double submit; this stops the drop looking accepted. */
          if (busy) return;
          const file = event.dataTransfer.files?.[0];
          if (!acceptedTerms) {
            rejectUnaccepted();
          } else if (file) {
            void handleFile(file);
          }
        }}
        className="drop"
      >
        <div>
          <p>drop an audio or video file here</p>
          <p className="hint">
            mp3, mp4, or mov — up to {MAX_FILE_SIZE_MB}mb &amp;{" "}
            {MAX_DURATION_SECONDS / 60} minutes
          </p>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy || checking || !acceptedTerms}
          aria-busy={checking || (pendingKind === "file" && submitting) || undefined}
          className="btn btn-secondary"
        >
          {pendingKind === "file" && submitting
            ? "sending…"
            : checking
              ? "checking…"
              : "browse file"}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".mp3,.mp4,.mov,audio/mpeg,video/mp4,video/quicktime"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (!acceptedTerms) {
              rejectUnaccepted();
            } else if (file) {
              void handleFile(file);
            }
            event.target.value = "";
          }}
        />
      </div>

      <label className="mt-[var(--space-sm)] flex items-start gap-[var(--space-2xs)] text-[0.72rem] leading-[1.6] text-[var(--color-muted)]">
        <input
          type="checkbox"
          checked={acceptedTerms}
          disabled={busy}
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
          className="mt-[0.2rem] h-3.5 w-3.5 shrink-0 accent-[var(--color-accent)]"
        />
        <span>
          I will only submit media I own or am authorized to process, and I agree to the{" "}
          <a className="text-[var(--color-accent)] underline underline-offset-2" href="/terms">
            Terms
          </a>{" "}
          and{" "}
          <a className="text-[var(--color-accent)] underline underline-offset-2" href="/privacy">
            Privacy Policy
          </a>
          .
        </span>
      </label>

      {/* `.error-note` is the named class for this exact recipe (`.pending-note`
          at danger ink) — see the four-rung ladder documented in globals.css.
          It used to be inlined here as arbitrary values, which meant the same
          rule lived in two places. */}
      {error && (
        <p id="intake-error" role="alert" className="error-note mt-[var(--space-xs)]">
          {error}
        </p>
      )}
    </>
  );
}
