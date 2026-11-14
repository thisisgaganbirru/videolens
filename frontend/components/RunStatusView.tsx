/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V5 */
/* Hallmark · component: run progress · genre: editorial · theme: custom (owner handoff)
 * Centred single column, direct children of HomeScreen's `.run-state`: status
 * pill, serif title, one-line lede, the filmstrip (one frame per backend
 * stage, sprocket holes top and bottom — or left and right once it stacks on a
 * phone), the source chip, then either the notice card with its actions
 * (failed, connection lost) with its actions centred under it, or the single
 * "stop watching" link. Drawn on design/shots/Progress*.png; the captions-only
 * state, the "File received" frame and the failed / lost notice follow
 * design/newshots/ (ProgressCaptions, ProgressUploadMobile, ProgressFailed,
 * ProgressLostWeb), which supersede the older shots where they differ.
 */

import { Check, WifiOff, X, ServerOff } from "lucide-react";
import type { RunStatus } from "@/domain/entities";
import { reconnectDelayFor, type LostCause, type MediaKind } from "@/application/useAnalysisRun";

type SourceKind = "file" | "url";

interface PipelineStep {
  /** matches the backend `stage` values exactly */
  stage: string;
  label: string;
  /** "The run stopped while …" */
  verb: string;
}

const DOWNLOAD_STEP: PipelineStep = {
  stage: "downloading",
  label: "Downloading",
  verb: "downloading",
};

/* Uploads' first frame (ProgressUploadMobile.png). The bytes have already
   arrived by the time a run exists, so it is done from the first paint; no
   backend stage ever names it. */
const FILE_STEP: PipelineStep = {
  stage: "file_received",
  label: "File received",
  verb: "receiving the file",
};

const SHARED_STEPS: PipelineStep[] = [
  { stage: "normalizing", label: "Normalizing", verb: "normalizing" },
  { stage: "uploading_to_gemini", label: "Uploading", verb: "uploading" },
  { stage: "analyzing", label: "Analyzing", verb: "analyzing" },
];

function stepsFor(sourceKind: SourceKind): PipelineStep[] {
  return [sourceKind === "url" ? DOWNLOAD_STEP : FILE_STEP, ...SHARED_STEPS];
}

/* `analyzing_captions` is the salvage path (backend process_run.py): every
   download route failed, so the backend fetched the caption track and went
   straight to analysis — normalizing and the Gemini upload never run. It has
   no frame of its own; it lands on Analyzing, and `captionsRoute` below
   redraws the frames before it (ProgressCaptions.png). */
const STAGE_ALIASES: Record<string, string> = {
  analyzing_captions: "analyzing",
};

/** Index of the frame for `stage`, or -1 when we cannot honestly place it. */
function frameIndex(steps: PipelineStep[], stage: string | null | undefined): number {
  if (!stage) return -1;
  const key = STAGE_ALIASES[stage] ?? stage;
  return steps.findIndex((step) => step.stage === key);
}

/* What to try next, chosen by *where the run died* rather than by what was
   submitted. The two differ, and the old `sourceKind` version got it wrong in
   the case that matters most: a run that downloaded, normalized and uploaded
   fine before Gemini returned 503 was told to "try a different URL", when a
   different URL would have failed in exactly the same place. Anything at or
   after the Gemini upload is ours, and saying so beats sending someone off to
   re-do work that was already good. */
/* Refinement 9 (item 11): a temporary block by the site (yt-dlp saw HTTP 403
   or 429) is not a bad link, so "try a different link" was the wrong next
   step. The run carries no reason code, only the backend's sentence, so this
   matches a stable phrase of it. It must stay in step with `_BLOCKED_DOWNLOAD`
   in backend/app/infrastructure/media/ytdlp_downloader.py; if that wording
   changes, this falls back to the ordinary download advice (still true, just
   less apt). A structured reason code on the run would retire this match. */
const BLOCKED_DOWNLOAD_PHRASE = "site blocked this download";

function isBlockedDownload(error: string | null | undefined): boolean {
  return !!error && error.toLowerCase().includes(BLOCKED_DOWNLOAD_PHRASE);
}

function recoveryAdvice(
  stage: string | null | undefined,
  sourceKind: SourceKind,
  error?: string | null
): string {
  const key = stage ? (STAGE_ALIASES[stage] ?? stage) : stage;
  /* Checked before the stage: the block can land before any stage was polled.
     The backend's sentence already gives the wait ("Try again in a few
     minutes"), so this line adds the other way through, not a second timing. */
  if (sourceKind === "url" && isBlockedDownload(error)) {
    return "You can try the same link again later, or download the video and upload the file instead.";
  }
  if (key === "uploading_to_gemini" || key === "analyzing") {
    /* ProgressFailed.png's copy. The server's own message ("Your file is
       fine…") follows in the notice below, so this line only says what to do. */
    return `You can try the same ${sourceKind === "url" ? "link" : "file"} again.`;
  }
  if (key === "downloading") {
    return "Try a different link, or download the video and upload the file instead.";
  }
  /* `normalizing`, or no stage at all: the media itself is the suspect, and
     the only thing we know about it is which way it arrived. */
  return sourceKind === "url" ? "Try a different link." : "Try a different file.";
}

/* Refinement 9: the heading and lede of a run in progress, by stage AND by
   what is being analyzed. It used to be "Reading your video" / "Longer files
   take more time to normalize" from queue to finish, which was wrong twice on
   an mp3 at Analyzing: no video, and no normalizing. The normalize hint now
   appears only while normalizing; "video" or "audio" only when the run is
   known to be one; otherwise the copy names neither. */
function progressCopy(
  stage: string | null | undefined,
  media: MediaKind | null,
  sourceKind: SourceKind
): { title: string; lede: string } {
  const noun = media ?? (sourceKind === "url" ? "link" : "file");
  const stay = "You can leave this open.";
  switch (stage ? (STAGE_ALIASES[stage] ?? stage) : null) {
    case "downloading":
      return {
        title: media ? `Downloading the ${media}` : "Downloading from the link",
        lede: `Fetching it from the link first. ${stay}`,
      };
    case "normalizing":
      return {
        title: `Preparing your ${noun}`,
        lede: `Longer files take more time to normalize. ${stay}`,
      };
    case "uploading_to_gemini":
      return {
        title: `Sending your ${noun} for analysis`,
        lede: `Uploading it to Gemini, which does the analysis. ${stay}`,
      };
    case "analyzing":
      return media === "audio"
        ? { title: "Listening to your audio", lede: `Transcribing it and writing the summary and notes. ${stay}` }
        : media === "video"
          ? {
              title: "Reading your video",
              lede: `Transcribing it, reading the text on screen, and writing the notes. ${stay}`,
            }
          : { title: `Analyzing your ${noun}`, lede: `Transcribing it and writing the summary and notes. ${stay}` };
    default:
      return { title: `Analyzing your ${noun}`, lede: `This can take a minute. ${stay}` };
  }
}

type FrameState = "done" | "active" | "waiting" | "failed" | "lost" | "missed" | "skipped";

const FRAME_CAPTION: Record<FrameState, string> = {
  done: "Done",
  active: "In progress",
  waiting: "Waiting",
  failed: "Stopped here",
  lost: "Waiting for connection",
  /* Captions route only: the download failed but the run carried on. */
  missed: "Couldn't download",
  skipped: "Skipped",
};

/** One frame's state. Reused shape of the old `stepStatus`: everything before
 *  the current frame is done, the current one carries the run's condition,
 *  everything after it waits. */
function stepStatus(
  index: number,
  currentIndex: number,
  status: RunStatus,
  connectionLost: boolean
): FrameState {
  if (status === "complete") return "done";
  if (currentIndex < 0) return "waiting";
  if (index < currentIndex) return "done";
  if (index > currentIndex) return "waiting";
  if (status === "failed") return "failed";
  // The last stage we heard about, held rather than animated: it is where the
  // run got to, not where it is.
  return connectionLost ? "lost" : "active";
}

/* The lost state when the server answered with an error (refinement 6). */
const SERVER_TROUBLE_PILL = "Server trouble";
const SERVER_TROUBLE_CAPTION = "Waiting for the server";

const PILL: Record<"queued" | "processing" | "failed" | "lost" | "complete", string> = {
  queued: "Queued",
  processing: "Processing",
  failed: "Failed",
  lost: "Connection lost",
  complete: "Complete",
};

interface RunStatusViewProps {
  status: RunStatus;
  stage?: string | null;
  sourceKind: SourceKind;
  error?: string | null;
  /** Polling threw. `useAnalysisRun` is now counting down to its next
   *  reconnect attempt; nothing on this screen advances until one succeeds. */
  connectionLost?: boolean;
  /** The link or file name, for the source chip. Absent for a run reopened
   *  from History before its metadata has arrived. */
  sourceLabel?: string | null;
  /** Whole seconds until the next automatic reconnect, ticking. */
  retryInSeconds?: number | null;
  /** A reconnect attempt is on the wire right now. */
  retrying?: boolean;
  /** Failed reconnect attempts so far (1-based). Drives the one polite
   *  announcement per attempt — never the per-second countdown. */
  reconnectAttempt?: number;
  /** Resubmitting the failed source is in flight. */
  retryBusy?: boolean;
  onReset?: () => void;
  /** Failed runs only, and only when there is a source to resubmit. */
  onRetry?: () => void;
  /** Connection lost only: skip the rest of the countdown. */
  onRetryNow?: () => void;
  /** Connection lost only: whether there was no answer at all (`network`)
   *  or the server answered with an error (`server`, refinement 6, RUN-08).
   *  The reconnect is the same; only the words differ. */
  lostCause?: LostCause;
  /** Failed only: the server forgot this run before its result reached this
   *  browser (refinement 1, #7). Not a failure of the source, so none of the
   *  "try a different link" advice and no stage strip — we never learned
   *  where it got to. */
  expired?: boolean;
  /** Expired only: why (2026-11-14). `server` (the default): the server
   *  forgot a live run. `saved`: a run listed as saved to the account is no
   *  longer there. */
  expiredReason?: "server" | "saved";
  /** Expired only: whether the link can be put back in the field. */
  canRefill?: boolean;
  /** Expired only: back to the intake (with the link filled, when stored). */
  onAnalyzeAgain?: () => void;
  /** Expired only: set when the run was opened from History (UX fix spec
   *  4.4); draws a "Back to History" button after the main one. */
  onBackToHistory?: () => void;
  /** Audio or video, when known (refinement 9): the progress copy names it. */
  mediaKind?: MediaKind | null;
  /** Failed only: the server's count proves this run did not use a free run
   *  (refinement 9, item 8). Never set on the user's own key. */
  freeRunRefunded?: boolean;
}

export default function RunStatusView({
  status,
  stage,
  sourceKind,
  error,
  connectionLost = false,
  sourceLabel,
  retryInSeconds = null,
  retrying = false,
  reconnectAttempt = 0,
  retryBusy = false,
  onReset,
  onRetry,
  onRetryNow,
  lostCause = "network",
  expired = false,
  expiredReason = "server",
  canRefill = false,
  onAnalyzeAgain,
  onBackToHistory,
  mediaKind = null,
  freeRunRefunded = false,
}: RunStatusViewProps) {
  if (status === "failed" && expired) {
    return (
      <ExpiredRunView
        reason={expiredReason}
        sourceKind={sourceKind}
        canRefill={canRefill}
        onAnalyzeAgain={onAnalyzeAgain ?? onReset}
        onBackToHistory={onBackToHistory}
      />
    );
  }

  const steps = stepsFor(sourceKind);
  const currentIndex = frameIndex(steps, stage);
  const current = currentIndex >= 0 ? steps[currentIndex] : null;
  /* The download failed and the run is reading captions instead. Only a link
     run can get here; the sourceKind check keeps a reopened run whose kind we
     could not tell from drawing "Couldn't download" over a file. */
  const captionsRoute = stage === "analyzing_captions" && sourceKind === "url";

  function frameState(step: PipelineStep, index: number): FrameState {
    if (step === FILE_STEP) return "done";
    if (captionsRoute && status !== "complete") {
      if (step === DOWNLOAD_STEP) return "missed";
      if (index < currentIndex) return "skipped";
    }
    return stepStatus(index, currentIndex, status, connectionLost);
  }

  /* Refinement 6 (RUN-08): a 5xx means the server is there and answering, so
     "Check your network" was the wrong advice. Same pill tone, countdown and
     Retry now; its own words. */
  const serverTrouble = connectionLost && lostCause === "server";

  const mode = connectionLost
    ? "lost"
    : status === "failed"
      ? "failed"
      : status === "complete"
        ? "complete"
        : status === "queued"
          ? "queued"
          : "processing";

  const progress = progressCopy(stage, mediaKind, sourceKind);

  const title =
    mode === "failed"
      ? "That didn't work"
      : mode === "lost"
        ? serverTrouble
          ? "The server is having trouble"
          : "Connection lost"
        : captionsRoute
          ? "Reading the captions"
          : mode === "queued"
            ? "In line"
            : progress.title;

  const lede =
    mode === "failed"
      ? `${current ? `The run stopped while ${current.verb}. ` : ""}${recoveryAdvice(stage, sourceKind, error)}`
      : mode === "lost"
        ? serverTrouble
          ? "It answered with an error, not a result. The page tries again on its own and picks up where it left off."
          : "Check your network. The page reconnects on its own and picks up where it left off."
        : mode === "queued"
          ? "Your run is in line and starts in a moment. You can leave this open."
          : captionsRoute
            ? "We couldn't download the video, so we are using its captions only. Results may have less detail."
            : progress.lede;

  /* One sentence per state change. While the connection is lost it changes
     once per failed attempt (`reconnectAttempt`), quoting that attempt's full
     wait — the visible countdown below ticks every second and is deliberately
     outside any live region. */
  const liveMessage =
    mode === "lost"
      ? retrying
        ? "Trying to reconnect."
        : `${serverTrouble ? "The server is having trouble." : "Connection lost."} Trying again in ${reconnectDelayFor(reconnectAttempt)} seconds.`
      : mode === "failed"
        ? `Analysis failed${error ? `: ${error}` : "."}`
        : mode === "complete"
          ? "Analysis complete."
          : `${PILL[mode]}${captionsRoute ? " — Analyzing captions" : current ? ` — ${current.label}` : ""}`;

  const countdown = retrying
    ? "Trying to reconnect…"
    : retryInSeconds !== null
      ? `Trying again in ${retryInSeconds} ${retryInSeconds === 1 ? "second" : "seconds"}.`
      : "";

  /* The four-frame strip. Its own constant because a failed run draws it
     under the reason and the buttons (UX fix spec 4.2) and every other mode
     above them. */
  const filmstrip = (
    <div className="filmstrip" data-mode={mode}>
      <ol className="filmstrip-frames" aria-label="Analysis steps">
        {steps.map((step, index) => {
          const state = frameState(step, index);
          return (
            <li
              key={step.stage}
              className="frame"
              data-state={state}
              aria-current={state === "active" ? "step" : undefined}
            >
              {state === "active" ? <span className="frame-scan" aria-hidden="true" /> : null}
              <span className="frame-num" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="frame-text">
                <span className="frame-label">{step.label}</span>
                <span className="frame-caption">
                {state === "lost" && serverTrouble ? SERVER_TROUBLE_CAPTION : FRAME_CAPTION[state]}
              </span>
              </span>
              <span className="frame-icon" aria-hidden="true">
                {state === "done" ? (
                  <Check size={18} strokeWidth={2.5} />
                ) : state === "failed" || state === "missed" ? (
                  <X size={18} strokeWidth={2.5} />
                ) : state === "lost" ? (
                  serverTrouble ? (
                    <ServerOff size={18} strokeWidth={2} />
                  ) : (
                    <WifiOff size={18} strokeWidth={2} />
                  )
                ) : null}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );

  /* Failed or connection lost: the message card, the refund line and the
     actions. */
  const stopBlock =
    mode === "failed" || mode === "lost" ? (
        /* ProgressFailed.png / ProgressLostWeb.png: the message in its own
           card, the actions centred under it (full width on a phone). */
        <>
          <p className="run-notice" data-tone={mode}>
            {mode === "failed"
              ? error || "The run stopped before it could finish."
              : serverTrouble
                ? `The server is having trouble right now. ${countdown}`
                : `We can't reach the server right now. ${countdown}`}
          </p>
          {/* Refinement 9 (item 8). Only when the server's re-read count is
              back to its pre-submit value. Always in the DOM on a failed run,
              so the polite region exists before the line lands (the check
              finishes a moment after the failure is shown). */}
          {mode === "failed" ? (
            <p className="run-refund" aria-live="polite">
              {freeRunRefunded ? "This didn't use one of your runs." : null}
            </p>
          ) : null}
          <div className="run-actions">
            {mode === "failed" && onRetry ? (
              <button
                type="button"
                className="btn btn-ink"
                onClick={onRetry}
                disabled={retryBusy}
                aria-busy={retryBusy || undefined}
              >
                {retryBusy ? "Starting…" : "Try again"}
              </button>
            ) : null}
            {mode === "lost" && onRetryNow ? (
              <button
                type="button"
                className="btn btn-ink"
                onClick={onRetryNow}
                disabled={retrying}
                aria-busy={retrying || undefined}
              >
                {retrying ? "Trying…" : "Retry now"}
              </button>
            ) : null}
            {onReset ? (
              /* Lost: the run is still going on the server, so this only
                 stops this page watching it (ProgressLostWeb's own label).
                 Failed: there is nothing left to watch. */
              <button type="button" className="btn btn-secondary" onClick={onReset}>
                {mode === "lost" ? "Stop watching" : "Analyze another"}
              </button>
            ) : null}
          </div>
        </>
    ) : null;

  return (
    <>
      <span className="status" data-tone={mode}>
        <span className="pip" aria-hidden="true" />
        {serverTrouble ? SERVER_TROUBLE_PILL : PILL[mode]}
      </span>

      <h1 className="run-title">{title}</h1>
      <p className="run-lede">{lede}</p>

      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {liveMessage}
      </p>

      {mode === "failed" ? (
        /* UX fix spec 4.2 (2026-11-14; departs from ProgressFailed.png, an
           owner decision): the reason and the way on come first, so both
           are in the first screen on a phone; the strip below still shows
           where the run stopped. */
        <>
          {stopBlock}
          {filmstrip}
        </>
      ) : (
        <>
          {filmstrip}

          {/* No chip once the run has stopped or gone quiet: ProgressFailed and
              ProgressLostWeb put the message card straight under the strip. */}
          {sourceLabel && mode !== "lost" ? (
            <p className="source-chip">
              <span className="source-chip__kind">{sourceKind === "url" ? "Link" : "File"}</span>
              <span className="source-chip__name">{sourceLabel}</span>
            </p>
          ) : null}

          {stopBlock ??
            (mode !== "complete" && onReset ? (
              /* "Cancel" on the boards, but reset only stops this page
                 watching — the server finishes the run regardless, and it
                 still lands in History. The label says what the button
                 actually does. */
              <button type="button" className="reset-link" onClick={onReset}>
                Stop watching and start another
              </button>
            ) : null)}
        </>
      )}
    </>
  );
}

/* Refinement 1, #7. A run reopened from History that the server had already
   dropped (it keeps runs an hour). The generic failed view told people to try
   a different link, which was wrong twice: nothing was wrong with the link,
   and the stages it drew were guesses. Pill, title, one honest sentence, the
   one action. */
function ExpiredRunView({
  reason,
  sourceKind,
  canRefill,
  onAnalyzeAgain,
  onBackToHistory,
}: {
  reason: "server" | "saved";
  sourceKind: SourceKind;
  canRefill: boolean;
  onAnalyzeAgain?: () => void;
  onBackToHistory?: () => void;
}) {
  const what = sourceKind === "url" ? "link" : "file";
  /* Refinement 9: "the server keeps a run for an hour" was only half the
     story — a server restart loses runs too, well inside the hour. This says
     what is true either way, without naming a cause we cannot know. */
  /* Saved history (2026-11-14): a saved run that answers 404 was deleted
     (perhaps on another device) or removed when the plan's 30 days ended.
     Either way it is not on the account any more; say that, not a cause. */
  if (reason === "saved") {
    const savedLede =
      sourceKind === "url" && canRefill
        ? "It may have been deleted on another device. The link is ready to analyze again."
        : sourceKind === "url"
          ? "It may have been deleted on another device. Paste the link again to start over."
          : "It may have been deleted on another device. Choose the file again to start over.";
    return (
      <>
        <span className="status" data-tone="failed">
          <span className="pip" aria-hidden="true" />
          Unavailable
        </span>
        <h1 className="run-title">This run is no longer saved</h1>
        <p className="run-lede">{savedLede}</p>
        <p className="sr-only" aria-live="polite" aria-atomic="true">
          This run is no longer saved to your account.
        </p>
        {onAnalyzeAgain || onBackToHistory ? (
          <div className="run-actions">
            {onAnalyzeAgain ? (
              <button type="button" className="btn btn-ink" onClick={onAnalyzeAgain}>
                {sourceKind === "url" || canRefill ? "Analyze it again" : `Choose the ${what} again`}
              </button>
            ) : null}
            {onBackToHistory ? (
              <button type="button" className="btn btn-secondary" onClick={onBackToHistory}>
                Back to History
              </button>
            ) : null}
          </div>
        ) : null}
      </>
    );
  }
  const gone = "The server no longer has this run, and its result never reached this browser.";
  const lede =
    sourceKind === "url"
      ? canRefill
        ? `${gone} Nothing was wrong with the link, and it is ready to analyze again.`
        : `${gone} Nothing was wrong with the link; paste it again to start over.`
      : `${gone} Nothing was wrong with the file; choose it again to start over.`;
  return (
    <>
      <span className="status" data-tone="failed">
        <span className="pip" aria-hidden="true" />
        Expired
      </span>
      <h1 className="run-title">This run expired</h1>
      <p className="run-lede">{lede}</p>
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        This run is no longer on the server, and its result never reached this browser.
      </p>
      {onAnalyzeAgain || onBackToHistory ? (
        <div className="run-actions">
          {onAnalyzeAgain ? (
            <button type="button" className="btn btn-ink" onClick={onAnalyzeAgain}>
              {sourceKind === "url" || canRefill ? "Analyze it again" : `Choose the ${what} again`}
            </button>
          ) : null}
          {onBackToHistory ? (
            <button type="button" className="btn btn-secondary" onClick={onBackToHistory}>
              Back to History
            </button>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
