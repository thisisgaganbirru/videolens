"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AnalysisCompleteness,
  FreeRunsStatus,
  HistoryRecord,
  MediaSource,
  RunStatus,
  RunSourceKind,
  RunStatusResponse,
  SavedRunSummary,
  SourceMetadata,
  VideoAnalysis,
} from "@/domain/entities";
import { classifyGatewayError } from "@/application/gatewayError";
import {
  EXPIRED_MESSAGE,
  isAccountOwned,
  isVisibleNow,
  isRunGone,
  OTHER_OWNER_MESSAGE,
  recordGone,
  recordRunResponse,
  recordSubmitted,
} from "@/application/historySync";
import {
  currentFreeRuns,
  markFreeRunsUsed,
  noteRunAccepted,
  refreshFreeRuns,
  revalidateFreeRuns,
  usingOwnKey,
} from "@/application/useFreeRuns";
import { ApiError } from "@/domain/errors";
import { markSavedRunGone } from "@/application/useSavedHistory";
import {
  activeRunStore,
  apiKeyStore,
  authSession,
  historyStore,
  runsGateway,
  savedHistoryGateway,
  sharedUrlSource,
} from "@/infrastructure/container";

const POLL_INTERVAL_MS = 3000;

/* Reconnect schedule after a poll throws: 4s, 8s, 16s, then every 30s until the
   user starts over. The first wait is short because most drops are a blip (a
   phone changing networks); the cap keeps a genuinely offline tab from
   hammering the server the moment it comes back, without ever giving up on a
   run that is still finishing server-side. */
const RECONNECT_DELAYS_S = [4, 8, 16, 30];

function reconnectDelay(attempt: number): number {
  return RECONNECT_DELAYS_S[Math.min(attempt, RECONNECT_DELAYS_S.length - 1)];
}

/** The full wait scheduled for the given 1-based `reconnectAttempt`, so the
 *  screen can announce "trying again in N seconds" once per attempt without
 *  reading the ticking countdown. */
export function reconnectDelayFor(reconnectAttempt: number): number {
  return reconnectDelay(Math.max(0, reconnectAttempt - 1));
}

/* What the progress screen calls the thing being analyzed before the server has
   said anything about it: the link as typed (minus the scheme), or the file's
   own name. Display only — never sent anywhere. */
function describeSource(source: MediaSource): string {
  if (source.file) return source.file.name;
  return source.url.replace(/^https?:\/\/(www\.)?/i, "").replace(/\/$/, "");
}

/* Fallbacks only — they are reached when the failure is neither a `NetworkError`
   nor an `ApiError`, i.e. when we genuinely do not know. A backend that is down
   gets the gateway's connectivity sentence and a backend that answered gets its
   own `detail`; describing either as "could not submit media" was the same
   dishonesty already fixed in `useRunHistory`. */
const SUBMIT_FALLBACK = "Could not submit media.";
const OPEN_FALLBACK = "Could not load that run.";
const POLL_FALLBACK = "Something went wrong.";
const SAVED_OPEN_FALLBACK = "That saved run could not be opened.";
/** Said when a run listed as saved to the account is no longer there (a 404
 *  on opening it): deleted on another device, or removed when the plan's
 *  30 days ran out. */
export const SAVED_GONE_MESSAGE = "This run is no longer saved to your account.";

/** How opening a saved run went, for History: `shown` (on Analyze now),
 *  `gone` (the unavailable view is on Analyze), `error` (nothing changed on
 *  screen; History says why), `stale` (something else was opened meanwhile). */
export type SavedOpenOutcome = { kind: "shown" | "gone" | "stale" } | { kind: "error"; message: string };

/** Why the expired view is showing: the server forgot a live run
 *  (`server`), or a run saved to the account is gone (`saved`). */
export type ExpiredReason = "server" | "saved";

/** Why the poll is down (refinement 6, RUN-08). `network`: no answer at all
 *  (offline, refused, DNS). `server`: the server answered, with an error
 *  (a 5xx, or a body this app could not read). Same reconnect either way;
 *  the screen just says the true thing. A 404 is neither: it is "expired". */
export type LostCause = "network" | "server";

/** What is being analyzed, for the progress copy (refinement 9): an mp3 run
 *  used to read "Reading your video". `null` when nothing says (a link to a
 *  site with no dedicated label, a reopened legacy run): the copy then names
 *  neither. */
export type MediaKind = "audio" | "video";

const AUDIO_EXTENSIONS = [".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"];

function mediaKindOfSource(source: MediaSource): MediaKind | null {
  if (source.file) {
    const name = source.file.name.toLowerCase();
    if (source.file.type.startsWith("audio/") || AUDIO_EXTENSIONS.some((ext) => name.endsWith(ext))) return "audio";
    return "video";
  }
  /* The three platforms the intake names are video platforms; anything else
     waits for the server's `platform`. */
  try {
    const host = new URL(source.url).hostname.replace(/^www\./, "");
    if (/(^|\.)(youtube\.com|youtu\.be|instagram\.com|tiktok\.com)$/.test(host)) return "video";
  } catch {
    /* not a URL; say nothing */
  }
  return null;
}

/** The server's word on the media, from the run's `platform`. */
function mediaKindOfPlatform(platform: string | null | undefined): MediaKind | null {
  if (platform === "audio_file") return "audio";
  if (platform === "video_file" || platform === "youtube" || platform === "instagram" || platform === "tiktok") {
    return "video";
  }
  return null;
}

/* Refinement 9 (item 8): the backend refunds the free run when a link fails to
   download or fails the duration cap after downloading. The app says "this
   didn't use a free run" ONLY when the server's own count proves it: the
   remaining count is back to what it was just before the submit, within the
   same UTC day (an unchanged `resetsAt`, so a midnight reset cannot pose as a
   refund). The refund is written just after the failure is (process_run's
   `finally`), so one late re-read covers the poll that lands between them. */
const REFUND_RECHECK_MS = 2500;

function provesRefund(before: FreeRunsStatus, after: FreeRunsStatus | null): boolean {
  return (
    after !== null &&
    before.enabled &&
    after.enabled &&
    /* A sign-in or sign-out between the two reads swaps whose count it is. */
    after.scope === before.scope &&
    after.resetsAt === before.resetsAt &&
    after.remaining === before.remaining
  );
}

/* 2026-11-20: a poll the server refuses for who is asking, not for the run.
   401/403: this sign-in is no longer accepted; 410: the account is in its
   deletion hold. Retrying cannot change either, so the poll stops instead of
   reconnecting forever, and the screen says what would. */
const SIGN_IN_ENDED =
  "This server no longer accepts your sign-in, so this run can’t be followed here. Sign in again from Account, then open it from History.";
const ACCOUNT_HELD =
  "Your account is scheduled for deletion, so this run can’t be shown. Restore your account from Account to see it.";

function accessEnded(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  if (err.status === 410) return ACCOUNT_HELD;
  if (err.status === 401 || err.status === 403) return SIGN_IN_ENDED;
  return null;
}

/* 2026-11-20: a 401 can be an access token that expired while the request
   was out. One quiet retry, this long after, asks the session for a token
   again (it refreshes an expired one) before the 401 counts as final.
   Nothing on screen changes for it. */
const AUTH_RETRY_MS = 1000;

function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

function lostCauseOf(err: unknown): LostCause {
  return classifyGatewayError(err, POLL_FALLBACK).kind === "server" ? "server" : "network";
}

export function useAnalysisRun() {
  const [status, setStatus] = useState<RunStatus | "idle">("idle");
  const [stage, setStage] = useState<string | null>(null);
  const [sourceKind, setSourceKind] = useState<"file" | "url">("file");
  const [mediaKind, setMediaKind] = useState<MediaKind | null>(null);
  /* Item 8: set only when the re-read count proves the failed run was not
     charged (see provesRefund). Never set on the user's own key. */
  const [freeRunRefunded, setFreeRunRefunded] = useState(false);
  const [result, setResult] = useState<VideoAnalysis | null>(null);
  /* Set only alongside `result`, never on a `processing` tick. It describes
     what the finished analysis was able to look at, so it is meaningless
     before there is one and would otherwise read `full` (the wire default)
     while the run was still deciding. */
  const [completeness, setCompleteness] = useState<AnalysisCompleteness>("full");
  const [sourceMetadata, setSourceMetadata] = useState<SourceMetadata | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  /* 2026-11-21: the run on screen has been answered for by the server since
     it was put there (accepted on submit, or a status response applied).
     False while `openRun` is still reading History or waiting for its first
     answer, so a run being reopened does not count as one being followed. */
  const [live, setLive] = useState(false);
  /* The link or file name of the run on screen, for the progress view's source
     chip. Known only for runs submitted in this session; a run reopened from
     History has none until its metadata arrives. */
  const [sourceName, setSourceName] = useState<string | null>(null);
  /* The media's length, from the run detail (or the History record), for the
     Source card of a file run (refinement 2, #6). */
  const [durationSeconds, setDurationSeconds] = useState<number | null>(null);
  /* The last submitted source, kept so a failed run can be retried with one
     press instead of re-pasting or re-picking. State rather than a ref because
     the screen reads it (whether to offer "Try again") during render. Cleared
     by reset and openRun — a run reopened from History has nothing to resubmit. */
  const [retrySource, setRetrySource] = useState<MediaSource | null>(null);
  /* Connection-lost bookkeeping. `reconnectIn` is whole seconds until the next
     automatic attempt (ticks once a second, for the visible countdown);
     `reconnecting` is true while an attempt is on the wire; `reconnectAttempt`
     counts failed attempts since the connection was last good and changes once
     per attempt — the polite announcement keys on it, so a screen reader hears
     one sentence per attempt rather than one per second. */
  const [reconnectIn, setReconnectIn] = useState<number | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const [lostCause, setLostCause] = useState<LostCause>("network");
  /* Refinement 1, #7: the run on screen is one the server forgot before its
     result reached this browser (History's EXPIRED_MESSAGE). Nothing about the
     source was wrong, so the failed view drops its "try a different link"
     advice and offers to analyze it again. `againUrl` is the link to put back
     in the field, when this browser stored one. */
  const [expired, setExpired] = useState<{ againUrl: string | null; reason?: ExpiredReason } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const runIdRef = useRef<string | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const attemptRef = useRef(0);
  /* Mirrors `submitting` for the guard below. State is read from a stale
     closure inside the same tick a second submit could arrive in; a ref is
     read at call time, which is what a re-entrancy guard needs. */
  const submittingRef = useRef(false);
  /* The link of the run being watched live, when it was submitted from a link
     in this session — what "Analyze it again" puts back if the server forgets
     the run mid-flight (refinement 3, #1). A ref because the poll's closure
     reads it; History holds the same value, but may be unavailable. */
  const liveUrlRef = useRef<string | null>(null);
  /* Bumped by every intent that replaces what is on screen — `submit`,
     `openRun`, `reset`. A request that was already in flight when the next
     intent arrived resolves into a screen that has moved on, so each one drops
     its result if the counter no longer matches the value it captured. Without
     it, a link shared mid-submit is undone a moment later by the 202 for the
     run the user just abandoned. The reconnect timers check it too. */
  const generationRef = useRef(0);
  /* The free-run allowance just before the live run was submitted, or null
     (own key, unknown, or a run reopened from History). Consumed by the
     failure check, so it is used at most once per submit. */
  const freeRunsBeforeRef = useRef<FreeRunsStatus | null>(null);
  const refundTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /* The upload in flight, so starting over or leaving the screen stops the
     bytes instead of finishing a run nobody is watching (2026-11-20). */
  const uploadRef = useRef<AbortController | null>(null);
  /* Opening a saved run fetches before it touches the screen, so it keeps
     its own token: a newer saved open drops an older one without retiring
     the live run's generation, which only moves once the detail is in. */
  const savedOpenRef = useRef(0);
  /* 2026-11-20: whether what is on screen (a result, a run in progress, an
     opened saved run) may belong to a signed-in account rather than to this
     device's anonymous caller. Read when the person signs out: an account's
     run must not stay on Analyze for the next person on the device. Unknown
     counts as the account's. */
  const accountScreenRef = useRef(false);
  /* 2026-11-21: the generation of an `openRun` still reading History's
     record (its owner not known yet), and the generation a sign-out arrived
     during that read. The sign-out's decision waits for the record, so an
     anonymous run being resumed is not cleared on a provisional guess. */
  const ownerPendingRef = useRef(-1);
  const deferredLeaveRef = useRef(-1);
  /* The one quiet retry after a 401 (see AUTH_RETRY_MS) is spent; any good
     response gives it back. */
  const authRetriedRef = useRef(false);

  /* Every timer this hook owns, stopped in one place: unmount, reset, openRun,
     a fresh submit and a successful reconnect all need exactly this. */
  const stopTimers = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    if (tickRef.current) clearInterval(tickRef.current);
    if (refundTimerRef.current) clearTimeout(refundTimerRef.current);
    pollRef.current = null;
    reconnectTimerRef.current = null;
    tickRef.current = null;
    refundTimerRef.current = null;
  }, []);

  /* Unmount also retires the generation, so a request still in flight (a
     resume started by a render that is being replaced) cannot write History
     or the active-run marker on its way back. */
  useEffect(
    () => () => {
      stopTimers();
      uploadRef.current?.abort();
      uploadRef.current = null;
      generationRef.current += 1;
    },
    [stopTimers]
  );

  const clearReconnect = useCallback(() => {
    attemptRef.current = 0;
    setReconnectIn(null);
    setReconnecting(false);
    setReconnectAttempt(0);
    setLostCause("network");
  }, []);

  const fail = useCallback((err: unknown, fallback: string) => {
    setError(classifyGatewayError(err, fallback).message);
  }, []);

  /* A run settled. Re-read the allowance either way (refinement 9, item 6),
     and for a failed live run, check whether it was refunded (item 8). */
  const settleFreeRuns = useCallback((failed: boolean) => {
    const before = freeRunsBeforeRef.current;
    freeRunsBeforeRef.current = null;
    const generation = generationRef.current;
    const check = (after: FreeRunsStatus | null) => {
      if (generationRef.current !== generation || !before || usingOwnKey()) return false;
      if (!provesRefund(before, after)) return false;
      setFreeRunRefunded(true);
      return true;
    };
    void revalidateFreeRuns().then((after) => {
      if (!failed || !before || check(after)) return;
      if (generationRef.current !== generation) return;
      refundTimerRef.current = setTimeout(() => {
        refundTimerRef.current = null;
        void revalidateFreeRuns().then(check);
      }, REFUND_RECHECK_MS);
    });
  }, []);

  /* One observed run response, applied to the screen. Returns true when the
     run has settled (complete or failed) — nothing left to poll for. Shared by
     the interval, a reconnect attempt and openRun so the three cannot disagree
     about what a response means. */
  const applyRun = useCallback((run: RunStatusResponse): boolean => {
    /* Every response the screen applies is also filed into this browser's
       History — that is how a run survives the server forgetting it. */
    recordRunResponse(run);
    authRetriedRef.current = false;
    setLive(true);
    setStatus(run.status);
    setStage(run.stage);
    const kind = mediaKindOfPlatform(run.platform);
    if (kind) setMediaKind(kind);
    if (run.source_metadata) setSourceMetadata(run.source_metadata);
    if (typeof run.duration_seconds === "number") setDurationSeconds(run.duration_seconds);
    /* `source_kind` is the server's record of how the run arrived, so when
       the response carries it, it decides — both ways. Runs stored before the
       field existed omit it; only then does the old inference apply: source
       metadata and these two stages only ever exist for link runs, so either
       one settles it (otherwise the progress strip would draw "File received"
       over a link). The inference never flips a link run back to "file". */
    if (run.source_kind === "link") {
      setSourceKind("url");
    } else if (run.source_kind === "file") {
      setSourceKind("file");
    } else if (run.source_metadata || run.stage === "downloading" || run.stage === "analyzing_captions") {
      setSourceKind("url");
    }
    if (run.status === "complete") {
      activeRunStore.clear();
      setResult(run.result);
      setCompleteness(run.completeness ?? "full");
      settleFreeRuns(false);
      return true;
    }
    if (run.status === "failed") {
      activeRunStore.clear();
      setError(run.error || "The analysis failed.");
      settleFreeRuns(true);
      return true;
    }
    return false;
  }, [settleFreeRuns]);

  /* Refinement 3, #1: the server answered 404 for a run this browser knows
     about — it forgot the run (past its hold, or a restart of an in-memory
     store). That is final, not a lost connection: stop every timer, file the
     History row as expired, and show the expired view with its normal
     actions. `knownUrl` is the link when the caller already has it; otherwise
     the one History stored is used once the write lands. */
  /* Auth phase 2: a 404 for a run History filed under a different identity
     (signed in as someone else, or signed out) is not an expiry. The server
     holds it for that caller; the screen says so and History is not
     touched, so switching back finds the run again (`recordGone`). */
  const expireRun = useCallback(
    async (runId: string, generation: number, knownUrl: string | null) => {
      stopTimers();
      clearReconnect();
      activeRunStore.clear();
      const outcome = await recordGone(runId);
      if (generationRef.current !== generation) return;
      setStatus("failed");
      setStage(null);
      if (outcome.kind === "other-owner") {
        setError(OTHER_OWNER_MESSAGE);
        setExpired(null);
        return;
      }
      setError(EXPIRED_MESSAGE);
      setExpired({ againUrl: knownUrl ?? outcome.againUrl });
    },
    [clearReconnect, stopTimers]
  );

  /* The server refused the poll for who is asking (see `accessEnded`). Final
     for this screen: every timer stops, nothing is filed into History (the
     run may be fine), and nothing offers to resubmit it. */
  const endAccess = useCallback(
    (message: string) => {
      stopTimers();
      clearReconnect();
      activeRunStore.clear();
      setRetrySource(null);
      setExpired(null);
      setStage(null);
      setStatus("failed");
      setError(message);
    },
    [clearReconnect, stopTimers]
  );

  /* `startPolling` and `scheduleReconnect` reach each other (a dead poll
     schedules a reconnect; a good reconnect resumes polling), so the second is
     called through a ref rather than a dependency cycle. */
  const scheduleReconnectRef = useRef<(generation: number) => void>(() => {});
  /* The quiet retry after a first 401 goes through a ref for the same reason. */
  const attemptReconnectRef = useRef<(generation: number) => void>(() => {});

  /** Takes a 401 as maybe an expired token, once: stops the poll and asks
   *  again shortly, saying nothing. False when it is not a 401 (or the retry
   *  is spent), so the caller treats the failure as it always has. */
  const retryUnauthorized = useCallback((runId: string, err: unknown, generation: number): boolean => {
    if (!isUnauthorized(err) || authRetriedRef.current) return false;
    authRetriedRef.current = true;
    runIdRef.current = runId;
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      attemptReconnectRef.current(generation);
    }, AUTH_RETRY_MS);
    return true;
  }, []);

  const startPolling = useCallback(
    (runId: string, generation: number) => {
      runIdRef.current = runId;
      /* Refinement 6 (RUN-06 web): this tab is now watching `runId`; a reload
         before it settles picks it back up (see `resume`). */
      activeRunStore.set(runId);
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const run = await runsGateway.getRun(runId);
          if (generationRef.current !== generation) return;
          if (applyRun(run) && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch (err) {
          if (generationRef.current !== generation) return;
          if (isRunGone(err)) {
            void expireRun(runId, generation, liveUrlRef.current);
            return;
          }
          if (retryUnauthorized(runId, err, generation)) return;
          const ended = accessEnded(err);
          if (ended) {
            endAccess(ended);
            return;
          }
          /* The interval stops, and the screen stops claiming progress:
             `HomeScreen` reads (error && status is queued or processing) as
             "connection lost". What changed is that this is no longer the end —
             a reconnect is scheduled and counted down on screen, and a good
             response puts the pipeline straight back. */
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          fail(err, POLL_FALLBACK);
          setLostCause(lostCauseOf(err));
          scheduleReconnectRef.current(generation);
        }
      }, POLL_INTERVAL_MS);
    },
    [applyRun, endAccess, expireRun, fail, retryUnauthorized]
  );

  const attemptReconnect = useCallback(
    async (generation: number) => {
      const runId = runIdRef.current;
      if (!runId || generationRef.current !== generation) return;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (tickRef.current) clearInterval(tickRef.current);
      reconnectTimerRef.current = null;
      tickRef.current = null;
      setReconnectIn(null);
      setReconnecting(true);
      try {
        const run = await runsGateway.getRun(runId);
        if (generationRef.current !== generation) return;
        setError(null);
        clearReconnect();
        if (!applyRun(run)) startPolling(runId, generation);
      } catch (err) {
        if (generationRef.current !== generation) return;
        if (isRunGone(err)) {
          void expireRun(runId, generation, liveUrlRef.current);
          return;
        }
        if (retryUnauthorized(runId, err, generation)) {
          setReconnecting(false);
          return;
        }
        const ended = accessEnded(err);
        if (ended) {
          endAccess(ended);
          return;
        }
        fail(err, POLL_FALLBACK);
        setLostCause(lostCauseOf(err));
        attemptRef.current += 1;
        scheduleReconnectRef.current(generation);
      }
    },
    [applyRun, clearReconnect, endAccess, expireRun, fail, retryUnauthorized, startPolling]
  );

  useEffect(() => {
    attemptReconnectRef.current = (generation: number) => void attemptReconnect(generation);
  }, [attemptReconnect]);

  const scheduleReconnect = useCallback(
    (generation: number) => {
      const delay = reconnectDelay(attemptRef.current);
      const due = Date.now() + delay * 1000;
      setReconnecting(false);
      setReconnectIn(delay);
      setReconnectAttempt(attemptRef.current + 1);
      if (tickRef.current) clearInterval(tickRef.current);
      /* A wall-clock deadline rather than a decrementing counter, so a
         throttled background tab shows the true time left when it comes back
         instead of a number that froze while it was hidden. */
      tickRef.current = setInterval(() => {
        setReconnectIn(Math.max(0, Math.ceil((due - Date.now()) / 1000)));
      }, 1000);
      reconnectTimerRef.current = setTimeout(() => {
        void attemptReconnect(generation);
      }, delay * 1000);
    },
    [attemptReconnect]
  );

  useEffect(() => {
    scheduleReconnectRef.current = scheduleReconnect;
  }, [scheduleReconnect]);

  /* "Retry now": skip the rest of the countdown. A no-op unless a reconnect is
     actually pending, so a double press cannot put two requests on the wire. */
  const reconnectNow = useCallback(() => {
    if (!reconnectTimerRef.current) return;
    void attemptReconnect(generationRef.current);
  }, [attemptReconnect]);

  /* Why this does NOT optimistically set `status: "queued"` before awaiting.
     That transition unmounts the idle branch, and with it `UploadForm`'s local
     `url` state; a rejected request then returned to idle and the field
     remounted empty, so "try again" meant "retype the URL". The status now
     changes exactly once, when the server has actually accepted the run — which
     is also the only point at which "queued" is true. `submitting` is what
     carries the intervening moment: it keeps the form mounted (input intact),
     disables its controls so there is no double-submit window, and gives the
     button a busy label so a successful submit still responds instantly. For a
     file upload the wait is the upload itself, which the old optimistic
     pipeline mislabelled as "normalizing" while the bytes were still leaving
     the browser. */
  const submit = useCallback(
    async (source: MediaSource) => {
      if (submittingRef.current) return;
      submittingRef.current = true;
      setSubmitting(true);
      stopTimers();
      clearReconnect();
      activeRunStore.clear();
      setError(null);
      setExpired(null);
      setResult(null);
      setCompleteness("full");
      setSourceMetadata(null);
      setDurationSeconds(null);
      setStage(null);
      setSourceKind(source.url ? "url" : "file");
      setMediaKind(mediaKindOfSource(source));
      setFreeRunRefunded(false);
      setLive(false);
      /* Taken before the request, so it is the count this run would spend
         from. Unknown (null) means no refund line can ever be claimed. */
      freeRunsBeforeRef.current = usingOwnKey() ? null : currentFreeRuns();
      const generation = ++generationRef.current;
      /* Whose run this is is known once the server accepts it. */
      accountScreenRef.current = true;
      authRetriedRef.current = false;
      uploadRef.current?.abort();
      const upload = new AbortController();
      uploadRef.current = upload;
      try {
        let run;
        try {
          run = await runsGateway.createRun(source, upload.signal);
        } catch (err) {
          /* Free runs (Phase 5b): the stored device token was missing or no
             longer valid. Read the allowance again — the adapter stores the
             fresh token the server issues — and send the same run once more.
             Once only: a second refusal is reported like any other. */
          if (!(err instanceof ApiError && err.code === "device_token_invalid")) throw err;
          await refreshFreeRuns();
          if (generationRef.current !== generation) return;
          run = await runsGateway.createRun(source, upload.signal);
        }
        /* Filed even if the screen has moved on: the run exists server-side
           and belongs in History either way. Under the identity this create
           request went out as. */
        recordSubmitted(run.run_id, run.status, source, run.owner);
        noteRunAccepted();
        if (generationRef.current !== generation) return;
        accountScreenRef.current = isAccountOwned(run.owner);
        setSourceName(describeSource(source));
        setRetrySource(source);
        liveUrlRef.current = source.url || null;
        setLive(true);
        setStatus(run.status);
        startPolling(run.run_id, generation);
      } catch (err) {
        /* Out of free runs. Marked even if the screen moved on, and even when
           the cached count still said runs were left — the 402 is the newer
           truth. No error line: the limit banner above the card says it, with
           the one action that fixes it, and the form stays as typed. */
        if (err instanceof ApiError && err.code === "free_runs_used") {
          markFreeRunsUsed(err.limit, err.used, err.scope);
          if (generationRef.current !== generation) return;
          /* A retry from the failed view lands here too; the banner lives on
             the intake, so go back to it. With a key saved the banner is
             hidden, so the server's own sentence is the only explanation. */
          setStatus("idle");
          if (apiKeyStore.get()) fail(err, SUBMIT_FALLBACK);
          return;
        }
        if (generationRef.current !== generation) return;
        fail(err, SUBMIT_FALLBACK);
      } finally {
        if (uploadRef.current === upload) uploadRef.current = null;
        submittingRef.current = false;
        setSubmitting(false);
      }
    },
    [clearReconnect, fail, startPolling, stopTimers]
  );

  const reset = useCallback(() => {
    /* Stop every timer first. The poll is `setStatus(run.status)` on a timer
       and a pending reconnect would revive it, so leaving either running meant
       "analyze another file" bounced straight back to the pipeline. */
    stopTimers();
    clearReconnect();
    activeRunStore.clear();
    /* Starting over cancels an upload still on its way. */
    uploadRef.current?.abort();
    uploadRef.current = null;
    runIdRef.current = null;
    liveUrlRef.current = null;
    generationRef.current += 1;
    freeRunsBeforeRef.current = null;
    accountScreenRef.current = false;
    authRetriedRef.current = false;
    setLive(false);
    setStatus("idle");
    setStage(null);
    setSourceKind("file");
    setMediaKind(null);
    setFreeRunRefunded(false);
    setResult(null);
    setCompleteness("full");
    setSourceMetadata(null);
    setSourceName(null);
    setDurationSeconds(null);
    setRetrySource(null);
    setError(null);
    setExpired(null);
  }, [clearReconnect, stopTimers]);

  /* 2026-11-20: signing out (here, by account deletion, "Continue signed
     out", or in another tab) takes an account's run off Analyze, so the next
     person on this device cannot read it; History hides the same rows
     (2026-11-21: hidden, not removed). Heard from the session itself, so every one of
     those paths is covered. The rules:
     - only after someone was signed in (or a session was stored) during
       this mount, so a person who never signed in keeps their own result;
     - only what may be an account's: an anonymous run on screen stays;
     - a session still stored but not recovered (an outage) is not a
       sign-out and changes nothing, and nor does a refused `/api/me` (a 503
       while the sign-in keys are down), which never touches the session;
     - another person signing in (in another tab) takes it off too. */
  useEffect(() => {
    if (!authSession.enabled) return;
    let lastUser = authSession.user()?.id ?? null;
    let accountSeen = authSession.hasSession();
    const leave = () => {
      /* An opened run whose owner History has not told us yet: decided once
         the record is read (openRun), not on the provisional guess. */
      if (ownerPendingRef.current === generationRef.current) {
        deferredLeaveRef.current = generationRef.current;
        return;
      }
      if (accountScreenRef.current) reset();
    };
    const onSessionChange = () => {
      const user = authSession.user();
      if (user) {
        const before = lastUser;
        lastUser = user.id;
        accountSeen = true;
        if (before && before !== user.id) leave();
        return;
      }
      if (authSession.hasSession()) {
        accountSeen = true;
        return;
      }
      lastUser = null;
      if (!accountSeen) return;
      accountSeen = false;
      leave();
    };
    return authSession.subscribe(onSessionChange);
  }, [reset]);

  /* `sourceKindHint` is the History summary's `source_kind`, when it has one,
     so a reopened run shows the right frames before its first status
     response lands. Absent (legacy rows), the run starts as "file" and
     `applyRun` corrects it.

     `resumed` (refinement 6, RUN-06 web): this is the run this tab was
     watching before a reload. The tab itself knows the run, so a 404 is
     "expired" even without a History record (IndexedDB may be blocked), and
     a failed read is a lost connection to reconnect from, not a reason to
     drop back to the intake. */
  const openRun = useCallback(
    async (runId: string, sourceKindHint?: RunSourceKind | null, { resumed = false }: { resumed?: boolean } = {}) => {
      stopTimers();
      clearReconnect();
      if (!resumed) activeRunStore.clear();
      setError(null);
      setResult(null);
      setCompleteness("full");
      setSourceMetadata(null);
      setSourceName(null);
      setDurationSeconds(null);
      setRetrySource(null);
      setExpired(null);
      liveUrlRef.current = null;
      freeRunsBeforeRef.current = null;
      setFreeRunRefunded(false);
      setMediaKind(null);
      setSourceKind(sourceKindHint === "link" ? "url" : "file");
      setLive(false);
      setStatus("processing");
      const generation = ++generationRef.current;
      /* Whose run: from History's record once it is read, unknown until
         then (and for an id History has no record of). A sign-out during the
         read waits for it (`ownerPendingRef`). */
      accountScreenRef.current = true;
      ownerPendingRef.current = generation;
      authRetriedRef.current = false;
      /* Whether this browser has its own record of the run. A 404 for one it
         knows means "expired"; for an id it has never seen it just means
         "not found" (refinement 3, #1). */
      let known = resumed;
      let knownUrl: string | null = null;
      /* History first: a finished run reopens from this browser with no
         network at all. Only a record without a result (still running, or
         one the store could not hold) falls through to the server. */
      let record: HistoryRecord | null = null;
      let readable = true;
      try {
        record = (await historyStore.get(runId)) ?? null;
      } catch {
        readable = false;
      }
      if (ownerPendingRef.current === generation) ownerPendingRef.current = -1;
      if (generationRef.current !== generation) return;
      /* 2026-11-21: a row hidden from whoever is signed in now (another
         account's, kept while it is signed out) is never shown, whether it
         was asked for from a stale History list or a resumed tab. Nothing is
         fetched for it and nothing is written; Analyze goes back to the
         intake. */
      if (record && !isVisibleNow(record.owner)) {
        if (deferredLeaveRef.current === generation) deferredLeaveRef.current = -1;
        reset();
        return;
      }
      accountScreenRef.current = record ? isAccountOwned(record.owner) : true;
      if (deferredLeaveRef.current === generation) {
        deferredLeaveRef.current = -1;
        /* Signed out (or someone else signed in) while the record was read:
           now that its owner is known, an account's run leaves Analyze. */
        if (accountScreenRef.current) {
          reset();
          return;
        }
      }
      if (readable) {
        if (record) {
          known = true;
          knownUrl = record.source_url ?? record.source_metadata?.source_url ?? null;
          if (record.source_kind) setSourceKind(record.source_kind === "link" ? "url" : "file");
          const recordKind = mediaKindOfPlatform(record.platform);
          if (recordKind) setMediaKind(recordKind);
        }
        /* A resumed link run gets back what the live run had: its link on
           the source chip, "Analyze it again" if it expires, and "Try again"
           if it fails. */
        if (resumed && knownUrl) {
          liveUrlRef.current = knownUrl;
          setSourceName(describeSource({ url: knownUrl }));
          setRetrySource({ url: knownUrl });
        }
        /* What this browser remembers about an upload: its name (never sent
           to or kept by the server) and its length. */
        if (record?.file_name) setSourceName(record.file_name);
        if (typeof record?.duration_seconds === "number") setDurationSeconds(record.duration_seconds);
        if (record && ((record.status === "complete" && record.result) || record.status === "failed")) {
          /* Settled while nobody was watching: nothing left to resume. */
          if (resumed) activeRunStore.clear();
          setSourceKind(record.source_kind === "link" ? "url" : "file");
          if (record.source_metadata) setSourceMetadata(record.source_metadata);
          setStatus(record.status);
          setStage(null);
          if (record.status === "complete") {
            setResult(record.result);
            setCompleteness(record.completeness ?? "full");
          } else {
            setError(record.error || "The analysis failed.");
            if (record.error === EXPIRED_MESSAGE) {
              setExpired({
                againUrl: record.source_url ?? record.source_metadata?.source_url ?? null,
              });
            }
          }
          return;
        }
      }
      /* (unreadable: no usable History here — ask the server as before) */
      try {
        const run = await runsGateway.getRun(runId);
        if (generationRef.current !== generation) return;
        if (!applyRun(run)) startPolling(runId, generation);
      } catch (err) {
        if (generationRef.current !== generation) return;
        if (known && isRunGone(err)) {
          runIdRef.current = runId;
          void expireRun(runId, generation, knownUrl);
          return;
        }
        if (retryUnauthorized(runId, err, generation)) return;
        const ended = accessEnded(err);
        if (ended) {
          runIdRef.current = runId;
          endAccess(ended);
          return;
        }
        if (resumed) {
          /* The run may well still be going; this tab just could not ask.
             The connection-lost screen, counting down to the next try. */
          runIdRef.current = runId;
          fail(err, POLL_FALLBACK);
          setLostCause(lostCauseOf(err));
          scheduleReconnectRef.current(generation);
          return;
        }
        setStatus("idle");
        fail(err, OPEN_FALLBACK);
      }
    },
    [applyRun, clearReconnect, endAccess, expireRun, fail, reset, retryUnauthorized, startPolling, stopTimers]
  );

  /* Refinement 6 (RUN-06 web): on a load of the app, pick up the run this tab
     was watching when it was reloaded, and show it (progress, result, failed
     or expired) instead of a fresh intake. Only when the load carries no
     other intent: a link shared in takes the intake, and an address naming
     another tab (`?view=history`) opens that tab. Returns whether it resumed. */
  const resume = useCallback((): boolean => {
    if (typeof window === "undefined") return false;
    const view = new URLSearchParams(window.location.search).get("view");
    if (view && view !== "analyze") return false;
    if (sharedUrlSource.pending()) return false;
    const runId = activeRunStore.get();
    if (!runId) return false;
    void openRun(runId, null, { resumed: true });
    return true;
  }, [openRun]);

  /* Paid saved history (2026-11-14): open a run saved to the account. This
     browser's own finished copy, when it has one, opens with no network (as
     History always has). Otherwise the saved detail is fetched *before*
     anything on screen changes, so a failure leaves History where it was
     and History can say why; a 404 shows the unavailable view.

     2026-11-20: the live run's generation moves only once the detail is in
     (or a 404 says it is gone). Taking it up front retired the run on
     Analyze before the fetch, so a failed open left that run's poll
     dropping every answer: frozen, with nothing on screen saying so. Until
     then a token of its own (`savedOpenRef`) tells a newer saved open from
     this one, and any other intent (a submit, a reset, a History open)
     moving the generation makes this one stale. */
  const openSavedRun = useCallback(
    async (summary: SavedRunSummary): Promise<SavedOpenOutcome> => {
      const token = ++savedOpenRef.current;
      const base = generationRef.current;
      const stale = () => savedOpenRef.current !== token || generationRef.current !== base;
      try {
        const record = await historyStore.get(summary.run_id);
        if (stale()) return { kind: "stale" };
        if (record?.status === "complete" && record.result) {
          void openRun(summary.run_id, record.source_kind);
          return { kind: "shown" };
        }
      } catch {
        /* no usable History here; ask the account */
      }
      if (stale()) return { kind: "stale" };
      const source = summary.source ?? null;
      /* The screen changes from here on, so the live run (if any) retires. */
      const resetScreen = () => {
        generationRef.current += 1;
        /* A run saved to the account is the account's. */
        accountScreenRef.current = true;
        authRetriedRef.current = false;
        stopTimers();
        clearReconnect();
        activeRunStore.clear();
        runIdRef.current = null;
        liveUrlRef.current = null;
        freeRunsBeforeRef.current = null;
        setFreeRunRefunded(false);
        setLive(false);
        setRetrySource(null);
        setSourceName(null);
        setStage(null);
        setSourceKind(source?.source_kind === "link" ? "url" : "file");
        setMediaKind(mediaKindOfPlatform(source?.platform ?? null));
        setDurationSeconds(typeof source?.duration_seconds === "number" ? source.duration_seconds : null);
      };
      try {
        const detail = await savedHistoryGateway.get(summary.run_id);
        if (stale()) return { kind: "stale" };
        const known = detail.source ?? source;
        resetScreen();
        setSourceKind(known?.source_kind === "link" ? "url" : "file");
        setSourceMetadata(
          known?.source_url
            ? {
                platform: known.platform ?? "other",
                source_url: known.source_url,
                title: known.source_title ?? null,
                uploader: known.uploader ?? null,
              }
            : null
        );
        setError(null);
        setExpired(null);
        setResult(detail.result);
        setCompleteness(detail.completeness === "captions_only" ? "captions_only" : "full");
        setStatus("complete");
        return { kind: "shown" };
      } catch (err) {
        if (stale()) return { kind: "stale" };
        if (err instanceof ApiError && err.status === 404) {
          /* Not redrawn now: History is on its way out and must not drop
             the card first. It is left out of the list next time. */
          markSavedRunGone(summary.run_id);
          resetScreen();
          setSourceMetadata(null);
          setResult(null);
          setCompleteness("full");
          setError(SAVED_GONE_MESSAGE);
          setExpired({ againUrl: source?.source_url ?? null, reason: "saved" });
          setStatus("failed");
          return { kind: "gone" };
        }
        /* Nothing on screen changed and the live run keeps going; History
           shows the message. */
        return { kind: "error", message: classifyGatewayError(err, SAVED_OPEN_FALLBACK).message };
      }
    },
    [clearReconnect, openRun, stopTimers]
  );

  /* Resubmit the run that just failed, same link or same file. Only offered
     while `canRetry` is true. */
  const retry = useCallback(() => {
    if (retrySource) void submit(retrySource);
  }, [retrySource, submit]);

  return {
    status,
    stage,
    sourceKind,
    mediaKind,
    freeRunRefunded,
    result,
    completeness,
    sourceMetadata,
    error,
    submitting,
    sourceName,
    durationSeconds,
    canRetry: retrySource !== null,
    expired: expired !== null,
    againUrl: expired?.againUrl ?? null,
    expiredReason: (expired?.reason ?? "server") as ExpiredReason,
    reconnectIn,
    reconnecting,
    reconnectAttempt,
    lostCause,
    /* 2026-11-21: whether signing in or out should wait. Only while a
       submit is on its way (it would be filed under the wrong owner) or a
       run the server has answered for is still going with no error. A run
       stalled on the connection-lost screen, reconnecting, or being reopened
       from History does not hold it. */
    holdsSignIn: submitting || ((status === "queued" || status === "processing") && !error && live),
    submit,
    retry,
    reconnectNow,
    reset,
    openRun,
    openSavedRun,
    resume,
  };
}
