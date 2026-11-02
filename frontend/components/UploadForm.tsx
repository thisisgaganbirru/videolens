"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import type { Capability, MediaSource } from "@/domain/entities";
import type { SharedUrl } from "@/application/useSharedUrl";
import { ArrowUpFromLine } from "lucide-react";
import { CapabilityCallout } from "@/components/CapabilityNotice";
import { isNoticeable } from "@/application/useCapabilities";

const ACCEPTED_EXTENSIONS = [".mp3", ".mp4", ".mov"];
const MAX_FILE_SIZE_MB = 200;
const MAX_DURATION_SECONDS = 180;
const MEDIA_TERMS_ACCEPTANCE_KEY = "videolens-media-terms-v1";

/* Storage can throw (private mode, blocked site data). Refinement 1 (#5): an
   unreadable flag reads as "not accepted" and an unwritable one is simply not
   remembered — the box still works for this visit. */
function readTermsAccepted(): boolean {
  try {
    return window.localStorage.getItem(MEDIA_TERMS_ACCEPTANCE_KEY) === "accepted";
  } catch {
    return false;
  }
}

function writeTermsAccepted(accepted: boolean): void {
  try {
    if (accepted) window.localStorage.setItem(MEDIA_TERMS_ACCEPTANCE_KEY, "accepted");
    else window.localStorage.removeItem(MEDIA_TERMS_ACCEPTANCE_KEY);
  } catch {
    /* not remembered; nothing else to do */
  }
}

interface UploadFormProps {
  onSubmit: (source: MediaSource) => void;
  disabled?: boolean;
  /** The submit request is in flight. Distinct from `disabled` because it also
   *  relabels the primary button: the form now stays mounted for the whole
   *  request (so a rejection does not wipe the typed URL), which means it is
   *  the form that has to show the wait. */
  submitting?: boolean;
  /** Out of free runs and no key saved (Phase 5b): the free-run banner above
   *  the card says so and offers "Add key". Analyze, Browse files and drop are
   *  all refused — none of them could succeed — but the link field stays
   *  editable, so a typed link survives saving a key and coming back. */
  blocked?: boolean;
  /** The most recent link shared into the app, or null. A new object per
   *  arrival, so re-sharing the same link still fills the field. `HomeScreen`
   *  owns the listener and has already returned the shell to a fresh intake by
   *  the time this lands; all this component does is take the value. */
  sharedUrl?: SharedUrl | null;
  /** The deployment's `url_download` row, when it has one and it is not ok.
   *  Comes from `HomeScreen` rather than a hook of this component's own — see
   *  the note there on why the report is fetched exactly once. */
  urlCapability?: Capability | null;
  /** A form-level failure from `useAnalysisRun` (the submit was rejected, the
   *  server could not be reached, a History row would not open). Shown as the
   *  first thing in the card. Not tied to the field: no aria-invalid, no
   *  focus move, so a network error never pulls focus out of the input. */
  submitError?: string | null;
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

export default function UploadForm({
  onSubmit,
  disabled,
  submitting,
  blocked,
  sharedUrl,
  urlCapability,
  submitError,
}: UploadFormProps) {
  const busy = disabled || submitting;
  /* Every way of starting a run. `busy` alone still governs the link field and
     the terms box, which stay usable while blocked. */
  const cannotStart = busy || blocked;
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
    setAcceptedTerms(readTermsAccepted());
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
    if (blocked) return;
    const value = url.trim();
    /* The button stays enabled with an empty field, as drawn on Main.png: a
       greyed-out primary action gives no reason, an error on press does. */
    if (!value) {
      setError("Paste a link to analyze.");
      document.getElementById("media-url")?.focus();
      return;
    }
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

  /* URL downloads are the one capability with a consequence the user can act
     on *at this control*, so it is said here rather than only in the summary
     strip above. It warns and never blocks: the probe reads a yt-dlp build
     date and whether a configured cookie file exists, neither of which proves
     the specific link the user is about to paste will fail. Disabling the
     field on that evidence would refuse URLs that work. */
  const urlNotice = urlCapability && isNoticeable(urlCapability.state) ? urlCapability : null;

  /* Wired as a description of the field rather than announced by a live
     region: it reaches a screen-reader user at the moment they focus the input
     — which is when it matters — instead of competing with the summary strip's
     announcement on load. */
  const describedBy = [error ? "intake-error" : null, urlNotice ? "url-capability" : null]
    .filter(Boolean)
    .join(" ");

  /* The intake card: one white surface holding both entry points and the
     terms row, drawn on design/shots/Main.png. HomeScreen owns everything
     around it (eyebrow, headline, lede, the "What you get" panel), so this
     component stays the form and nothing else. */
  return (
    <div className="intake-card">
      {/* The owner wanted the submit error inside the card, above "Paste a
          link" — the control that failed is right below it. Rendered only
          when present, so the card is unchanged without it. */}
      {submitError ? (
        <p role="alert" className="intake-alert">
          {submitError}
        </p>
      ) : null}
      <form onSubmit={submitUrl} className="link-form">
        <label htmlFor="media-url" className="intake-card__label">
          Paste a link
        </label>
        <div className="link-row">
          <input
            id="media-url"
            type="url"
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
              setError(null);
            }}
            placeholder="YouTube, TikTok, or Instagram link"
            autoComplete="url"
            disabled={busy}
            aria-invalid={error ? "true" : undefined}
            aria-describedby={describedBy || undefined}
            className="field"
          />
          <button
            type="submit"
            disabled={cannotStart}
            aria-busy={pendingKind === "url" && submitting ? true : undefined}
            className="btn btn-primary"
          >
            {pendingKind === "url" && submitting ? "Sending…" : "Analyze link"}
          </button>
        </div>
      </form>

      {urlNotice && (
        <div id="url-capability" className="cap-field-note">
          <CapabilityCallout
            capability={urlNotice}
            lead={urlNotice.state === "unavailable" ? "Link runs are unavailable" : "Link runs may fail"}
          />
        </div>
      )}

      <div className="divider" aria-hidden="true">
        or
      </div>

      <div
        data-dragging={dragActive ? "true" : undefined}
        data-blocked={blocked ? "true" : undefined}
        onDragOver={(event) => {
          event.preventDefault();
          /* Out of free runs: say "no" with the cursor rather than lighting
             the zone up as if the drop would be taken. */
          if (blocked) {
            event.dataTransfer.dropEffect = "none";
            return;
          }
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          /* The drop zone has no disabled state of its own, so it is the one
             entry point that could still fire mid-submit. The hook guards
             against the double submit; this stops the drop looking accepted. */
          if (cannotStart) return;
          const file = event.dataTransfer.files?.[0];
          if (!acceptedTerms) {
            rejectUnaccepted();
          } else if (file) {
            void handleFile(file);
          }
        }}
        className="drop"
      >
        <span className="drop-icon" aria-hidden="true">
          <ArrowUpFromLine size={20} strokeWidth={2} />
        </span>
        {/* Two titles, one shown: "drop" is a lie on a touch screen, where the
            only way in is the button. The swap is a hover/pointer media query
            in globals.css; `display: none` keeps the hidden one out of the
            accessibility tree too. */}
        <div className="drop-text">
          <p className="drop-title">
            <span className="drop-title--pointer">Drop an audio or video file</span>
            <span className="drop-title--touch">Add an audio or video file</span>
          </p>
          <p className="hint">
            MP3, MP4, or MOV. Up to {MAX_FILE_SIZE_MB} MB and {MAX_DURATION_SECONDS / 60} minutes.
          </p>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={cannotStart || checking || !acceptedTerms}
          aria-busy={checking || (pendingKind === "file" && submitting) || undefined}
          className="btn btn-secondary"
        >
          {pendingKind === "file" && submitting
            ? "Sending…"
            : checking
              ? "Checking…"
              : "Browse files"}
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

      <label className="terms-row">
        <input
          type="checkbox"
          checked={acceptedTerms}
          disabled={busy}
          onChange={(event) => {
            const accepted = event.target.checked;
            setAcceptedTerms(accepted);
            writeTermsAccepted(accepted);
            setError(null);
          }}
        />
        <span>
          I will only submit media I own or am allowed to process, and I agree to the{" "}
          <a className="text-link" href="/terms">
            Terms
          </a>{" "}
          and{" "}
          <a className="text-link" href="/privacy">
            Privacy Policy
          </a>
          .
        </span>
      </label>

      {/* `.error-note` is the named class for this exact recipe (`.pending-note`
          at danger ink) — see the four-rung ladder documented in globals.css. */}
      {error && (
        <p id="intake-error" role="alert" className="error-note">
          {error}
        </p>
      )}
    </div>
  );
}
