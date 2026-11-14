"use client";

import { FormEvent, useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import type { Capability, MediaLimits, MediaSource, FreeRunsPeriod } from "@/domain/entities";
import type { SharedUrl } from "@/application/useSharedUrl";
import { ArrowUpFromLine } from "lucide-react";
import { CapabilityCallout } from "@/components/CapabilityNotice";
import { isNoticeable } from "@/application/useCapabilities";
import { revealField } from "@/application/useSoftKeyboard";
import { goToMainTab, mainTabHref } from "@/application/useMainTab";
import { FALLBACK_LIMITS, durationLabel } from "@/application/useMediaLimits";
import { ACCOUNT_FREE_RUNS_PER_DAY, PAID_RUNS_PER_DAY } from "@/application/accountAllowance";
import { isPlainLeftClick } from "@/components/navClick";
import { MEDIA_FILE_ACCEPT, readTermsAccepted, writeTermsAccepted } from "@/components/mediaTerms";

/** Something the shell hands the freshly mounted intake (refinement 9): a file
 *  picked from the expired view's "Choose the file again", to run through the
 *  same checks as Browse; or the terms error, when that tap found the terms
 *  unticked. A new object per hand-off. */
export type IntakeHandoff = { kind: "file"; file: File } | { kind: "terms" };

const ACCEPTED_EXTENSIONS = [".mp3", ".mp4", ".mov"];
interface UploadFormProps {
  onSubmit: (source: MediaSource) => void;
  disabled?: boolean;
  /** The submit request is in flight. Distinct from `disabled` because it also
   *  relabels the primary button: the form now stays mounted for the whole
   *  request (so a rejection does not wipe the typed URL), which means it is
   *  the form that has to show the wait. */
  submitting?: boolean;
  /** Out of runs and no key saved (Phase 5b): the strip above the card says
   *  so, and the card offers the way out (`blockedOffer`). Analyze, Browse files and drop are
   *  all refused — none of them could succeed — but the link field stays
   *  editable, so a typed link survives saving a key and coming back. */
  blocked?: boolean;
  /** The period of the allowance that is spent when `blocked`: `day`
   *  (default; a device or, since 2026-11-14, a free account) or `month`.
   *  Kept for callers; since 2026-11-14 the blocked note no longer names it. */
  blockedPeriod?: FreeRunsPeriod;
  /** What to offer when `blocked`. */
  blockedOffer?: "sign-in" | "upgrade" | "key"; // default "key"
  /** Not blocked yet, but it may be once the allowance answers
   *  (2026-11-14): an unseen, inert copy of the block holds its space when
   *  the pre-paint `data-runs-spent` stamp says this device was out of runs
   *  last time (CSS picks the copy for the stamped offer; otherwise it takes
   *  no space). */
  blockedHeld?: boolean;
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
  /** See IntakeHandoff. Taken once: `onHandoffTaken` tells the owner to drop
   *  it, so a later remount of the form cannot replay it. */
  handoff?: IntakeHandoff | null;
  onHandoffTaken?: () => void;
  /** The upload limits for this person (`useMediaLimits`, 2026-11-13): the
   *  hint under the drop title and the pre-upload checks both use them. The
   *  server re-checks every upload. Defaults to the standard limits. */
  limits?: MediaLimits;
  /** Set (to the larger tier's minutes) only where sign-in is offered and a
   *  key is saved but nobody is signed in: one quiet line under the limits
   *  says signing in allows longer videos. */
  signInForMinutes?: number | null;
}

type ErrorField = "url" | "file" | "terms";
type FieldErrors = Partial<Record<ErrorField, string>>;
/** DOM order of the three controls: the first invalid one takes focus. */
const FIELD_ORDER: ErrorField[] = ["url", "file", "terms"];
const TERMS_MESSAGE = "Accept the media-use terms before analysis.";

function validateFile(file: File, maxFileSizeMb: number): string | null {
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!ACCEPTED_EXTENSIONS.includes(ext)) {
    return "Only MP3, MP4, and MOV files are supported.";
  }
  /* Refinement 6 (INT-16): a 0-byte file used to be POSTed and refused by the
     server a round trip later. Nothing in it can be analyzed. */
  if (file.size === 0) {
    return "This file is empty. Choose another one.";
  }
  if (file.size > maxFileSizeMb * 1024 * 1024) {
    return `File is larger than the ${maxFileSizeMb}MB limit.`;
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
  blockedOffer = "key",
  blockedHeld = false,
  sharedUrl,
  urlCapability,
  submitError,
  handoff,
  onHandoffTaken,
  limits = FALLBACK_LIMITS.standard,
  signInForMinutes = null,
}: UploadFormProps) {
  const { maxDurationSeconds, maxFileSizeMb } = limits;
  const busy = disabled || submitting;
  /* Every way of starting a run. `busy` alone still governs the link field and
     the terms box, which stay usable while blocked. */
  const cannotStart = busy || blocked;
  const [url, setUrl] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [checking, setChecking] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  /* One message per control, each shown right under the control it is about.
     Only a link error marks the link field invalid (red border,
     aria-invalid): the terms error is about the checkbox, and a file error
     about a file the field never saw (refinement 2, #4). Refinement 4
     (INT-01/03/05): each message is its control's aria-describedby, and the
     control plus message are scrolled into view. Refinement 6 (INT-04): a
     map rather than one slot, so a press of Analyze with an empty link AND
     the terms unticked says both at once instead of one per press. */
  const [errors, setErrors] = useState<FieldErrors>({});
  /* Bumped on every rejection, so pressing Analyze twice on the same empty
     field brings it back into view the second time too. */
  const [errorSeq, setErrorSeq] = useState(0);
  const revealRef = useRef<ErrorField | null>(null);
  /** Replace the shown errors with `next`, and focus + reveal the first of
   *  them in DOM order (link, file, terms). */
  const showErrors = useCallback((next: FieldErrors) => {
    const first = FIELD_ORDER.find((field) => next[field]);
    if (!first) return;
    setErrors(next);
    revealRef.current = first;
    setErrorSeq((n) => n + 1);
  }, []);
  const showError = useCallback(
    (message: string, field: ErrorField) => showErrors({ [field]: message }),
    [showErrors]
  );
  /** Drop one control's message (it was edited), or all of them. */
  const clearError = useCallback((field?: ErrorField) => {
    setErrors((current) => {
      if (!field) return Object.keys(current).length ? {} : current;
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }, []);
  /* Which of the two entry points is waiting. Both are disabled while a submit
     is in flight, but only the one the user actually pressed should say so —
     "sending…" on both reads as two things happening at once. */
  const [pendingKind, setPendingKind] = useState<"url" | "file" | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const termsRef = useRef<HTMLInputElement>(null);
  const browseRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!submitting) setPendingKind(null);
  }, [submitting]);

  /* After the message has rendered: move focus to the control it is about
     (the link field, or the terms box) and bring the pair into view. A file
     error leaves focus alone — the picker just closed, and Browse files is
     already where the user is — but is still scrolled to. Focusing the link
     field opens the keyboard on a phone; useSoftKeyboard then re-reveals the
     same group once the keyboard has taken its room. */
  useEffect(() => {
    const field = revealRef.current;
    revealRef.current = null;
    if (errorSeq === 0 || !field) return;
    const target = field === "url" ? urlRef.current : field === "terms" ? termsRef.current : browseRef.current;
    if (!target) return;
    if (field !== "file") target.focus({ preventScroll: true });
    revealField(target);
  }, [errorSeq]);

  useEffect(() => {
    setAcceptedTerms(readTermsAccepted());
  }, []);

  /* Runs on mount too, which is the case that matters: a share arriving over a
     finished result remounts this form (HomeScreen resets the run), and the
     link has to be waiting in the field when it comes back. */
  useEffect(() => {
    if (!sharedUrl) return;
    setUrl(sharedUrl.url);
    setErrors({});
  }, [sharedUrl]);

  const handleFile = useCallback(
    async (file: File) => {
      const validationError = validateFile(file, maxFileSizeMb);
      if (validationError) {
        showError(validationError, "file");
        return;
      }

      clearError();
      setChecking(true);
      try {
        const duration = await readMediaDuration(file);
        if (duration > maxDurationSeconds) {
          showError(
            `Media is ${Math.round(duration)}s long, which exceeds the ${durationLabel(maxDurationSeconds)} limit.`,
            "file"
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
    [clearError, maxDurationSeconds, maxFileSizeMb, onSubmit, showError]
  );

  const submitUrl = (event: FormEvent) => {
    event.preventDefault();
    if (blocked) return;
    const value = url.trim();
    /* The button stays enabled with an empty field, as drawn on Main.png: a
       greyed-out primary action gives no reason, an error on press does.
       Every check runs and every failure shows at once (refinement 6,
       INT-04); focus goes to the first one in DOM order. */
    const next: FieldErrors = {};
    if (!value) next.url = "Paste a link to analyze.";
    else {
      const validationError = validateUrl(value);
      if (validationError) next.url = validationError;
    }
    if (!acceptedTerms) next.terms = TERMS_MESSAGE;
    if (next.url || next.terms) {
      showErrors(next);
      return;
    }
    clearError();
    setPendingKind("url");
    onSubmit({ url: value });
  };

  const rejectUnaccepted = useCallback(() => {
    showError(TERMS_MESSAGE, "terms");
  }, [showError]);

  /* Refinement 9: the expired view opened the picker itself, inside the tap
     (a picker cannot be opened from a later render), and has already applied
     the terms gate. A chosen file still gets every check Browse gives it. */
  useEffect(() => {
    if (!handoff) return;
    onHandoffTaken?.();
    /* Both paths run after the effect, like a picker's change event would:
       the hand-off is an event from outside this form, not state to derive. */
    const picked = handoff;
    queueMicrotask(() => {
      if (picked.kind === "terms") rejectUnaccepted();
      else void handleFile(picked.file);
    });
  }, [handoff, handleFile, onHandoffTaken, rejectUnaccepted]);

  /* Refinement 8: Browse files used to be disabled until the terms were
     ticked, a dimmed control with no reason given, while Analyze link
     explained itself on press (refinement 6). Now the two paths behave the
     same: Browse stays live, and pressing it with the terms unticked opens
     no picker; it shows the terms error, marks and focuses the checkbox and
     brings it into view. Once ticked, it opens the picker, and a chosen file
     goes straight to handleFile (there is no separate submit button). */
  const browse = () => {
    if (!acceptedTerms) {
      rejectUnaccepted();
      return;
    }
    inputRef.current?.click();
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
  const describedBy = [errors.url ? "url-error" : null, urlNotice ? "url-capability" : null]
    .filter(Boolean)
    .join(" ");

  /* Refinement 9 (item 3): out of free runs, Analyze link and Browse files
     are disabled — and the only explanation used to be the banner above the
     headline, off screen once the form is scrolled to. This line sits in the
     card and is each disabled control's description. */
  const blockedNote = blocked ? "intake-blocked" : null;
  const openApiKey = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainLeftClick(event)) return;
    event.preventDefault();
    goToMainTab("api-key");
  };
  const openAccount = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainLeftClick(event)) return;
    event.preventDefault();
    goToMainTab("account");
  };

  /* The intake card: one white surface holding both entry points and the
     terms row, drawn on design/shots/Main.png. HomeScreen owns everything
     around it (the allowance strip, the "New analysis" title, the retention
     line under the card), so this component stays the form and nothing
     else. */
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
      {blocked ? (
        /* UX fix spec (2026-11-14): the one way out, in the order the
           business wants it offered: sign in (signed out, where sign-in
           works), upgrade (a free account where the plan is sold), else the
           Gemini key. One green button at most; Analyze link is disabled, so
           this is the screen's one enabled filled button. */
        <BlockedBlock id="intake-blocked" offer={blockedOffer} onApiKey={openApiKey} onAccount={openAccount} />
      ) : blockedHeld ? (
        <div className="intake-blocked-ghost" aria-hidden="true" inert>
          <BlockedBlock offer="key" />
          <BlockedBlock offer="sign-in" />
        </div>
      ) : null}
      {/* noValidate: the field is type="url" for the keyboard and autofill,
          but the browser's own "Please enter a URL." bubble would pre-empt
          the app's messages below (refinement 2, #4). submitUrl validates. */}
      <form onSubmit={submitUrl} className="link-form" noValidate data-reveal-group>
        <label htmlFor="media-url" className="intake-card__label">
          Paste a public link
        </label>
        <div className="link-row">
          <input
            ref={urlRef}
            id="media-url"
            type="url"
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
              clearError("url");
            }}
            placeholder="YouTube, TikTok, or Instagram link"
            autoComplete="url"
            disabled={busy}
            aria-invalid={errors.url ? "true" : undefined}
            aria-describedby={describedBy || undefined}
            className="field"
          />
          <button
            type="submit"
            disabled={cannotStart}
            aria-describedby={blockedNote ?? undefined}
            aria-busy={pendingKind === "url" && submitting ? true : undefined}
            className="btn btn-primary"
          >
            {pendingKind === "url" && submitting ? "Sending…" : "Analyze link"}
          </button>
          {errors.url && (
            <p id="url-error" role="alert" className="error-note field-error">
              {errors.url}
            </p>
          )}
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

      <div data-reveal-group>
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
          /* Only a dropped file is a start; dragged text or a link does
             nothing, and in particular does not raise the terms error. */
          const file = event.dataTransfer.files?.[0];
          if (!file) return;
          if (!acceptedTerms) rejectUnaccepted();
          else void handleFile(file);
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
            <span className="only-pointer">Drop an audio or video file</span>
            <span className="only-touch">Add an audio or video file</span>
          </p>
          <p className="hint">
            MP3, MP4, or MOV. Up to {maxFileSizeMb}{" "}MB and {durationLabel(maxDurationSeconds)}.
          </p>
          {/* 2026-11-13: a key is saved but nobody is signed in, and signing
              in would lift the limits. One quiet line in the same hint
              voice; HomeScreen decides when it applies. */}
          {signInForMinutes ? (
            <p className="hint">
              <a className="text-link" href={mainTabHref("account")} onClick={openAccount}>
                Sign in
              </a>{" "}
              for videos up to {signInForMinutes} minutes.
            </p>
          ) : null}
        </div>
        <button
          ref={browseRef}
          type="button"
          onClick={browse}
          disabled={cannotStart || checking}
          aria-busy={checking || (pendingKind === "file" && submitting) || undefined}
          aria-describedby={[errors.file ? "file-error" : null, blockedNote].filter(Boolean).join(" ") || undefined}
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
          accept={MEDIA_FILE_ACCEPT}
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
      {errors.file && (
        <p id="file-error" role="alert" className="error-note field-error">
          {errors.file}
        </p>
      )}
      </div>

      <div data-reveal-group>
      <label className="terms-row">
        {/* Refinement 6 (A11-13): the box is drawn 20x20, but this wrapper
            is a 44x44 tap target around it (negative margins, so the row
            does not move). It is inside the label, so a tap anywhere on it
            toggles the box. */}
        <span className="terms-box">
          <input
            ref={termsRef}
            type="checkbox"
            checked={acceptedTerms}
            disabled={busy}
            aria-invalid={errors.terms ? "true" : undefined}
            aria-describedby={errors.terms ? "terms-error" : undefined}
            onChange={(event) => {
              const accepted = event.target.checked;
              setAcceptedTerms(accepted);
              writeTermsAccepted(accepted);
              clearError("terms");
            }}
          />
        </span>
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

      {errors.terms && (
        <p id="terms-error" role="alert" className="error-note field-error">
          {errors.terms}
        </p>
      )}
      </div>
    </div>
  );
}

/* The out-of-runs block. Rendered for real when blocked, and as an unseen
   stand-in (no id, no handlers, inside an inert wrapper) while it may be. */
function BlockedBlock({
  id,
  offer,
  onApiKey,
  onAccount,
}: {
  id?: string;
  offer: "sign-in" | "upgrade" | "key";
  onApiKey?: (event: MouseEvent<HTMLAnchorElement>) => void;
  onAccount?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  return (
    <div id={id} className="intake-blocked" data-offer={offer === "key" ? "key" : "pair"}>
      <p className="intake-blocked__text">Analyzing is paused until your runs reset.</p>
      <div className="intake-blocked__actions">
        {offer === "key" ? (
          <a className="btn btn-secondary btn-pill" href={mainTabHref("api-key")} onClick={onApiKey}>
            Use your own Gemini key
          </a>
        ) : (
          <>
            <a className="btn btn-primary btn-pill" href={mainTabHref("account")} onClick={onAccount}>
              {offer === "sign-in"
                ? `Sign in for ${ACCOUNT_FREE_RUNS_PER_DAY} runs a day`
                : `Upgrade to Plus for ${PAID_RUNS_PER_DAY} runs a day`}
            </a>
            <a className="text-link" href={mainTabHref("api-key")} onClick={onApiKey}>
              Use your own Gemini key
            </a>
          </>
        )}
      </div>
    </div>
  );
}
