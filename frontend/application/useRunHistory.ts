"use client";

import { useCallback, useEffect, useState } from "react";
import type { RunSummary } from "@/domain/entities";
import { classifyGatewayError, type GatewayError, type GatewayErrorKind } from "@/application/gatewayError";
import { runsGateway } from "@/infrastructure/container";

/* Why a kind and not just a string: the old hook collapsed every failure into
   "Could not load history.", which was reachable only when the request never
   reached a server — so the one case it described was the one case it got
   wrong. The gateway now distinguishes the two; this keeps them distinct all
   the way to the panel so each can be worded honestly.

   The classifier itself was lifted to `application/gatewayError.ts` when
   `useAnalysisRun` needed the same treatment — these two aliases keep this
   hook's public vocabulary unchanged for `HistoryPanel`. */
export type RunHistoryErrorKind = GatewayErrorKind;

export type RunHistoryError = GatewayError;

const UNKNOWN_FALLBACK = "History could not be loaded.";

export function useRunHistory() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<RunHistoryError | null>(null);
  const [retrying, setRetrying] = useState(false);
  /* The retry mechanism: bumping this re-runs the effect. The alternative —
     an async callback that duplicates the fetch — would have two code paths
     to keep in step, and the mount path is the one that already exists. */
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    runsGateway
      .listRuns()
      .then((response) => {
        if (cancelled) return;
        setRuns(response.runs);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(classifyGatewayError(err, UNKNOWN_FALLBACK));
      })
      .finally(() => {
        if (!cancelled) setRetrying(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => {
    /* Guarded rather than disabling the button: a focused element that becomes
       `disabled` is blurred to <body> by the browser, so a keyboard user who
       hits Retry loses their place. The control stays focusable and marks
       itself `aria-disabled` while a request is in flight. The guard reads
       state directly instead of living inside a setState updater — updaters
       have to be pure, and StrictMode double-invokes them in dev. */
    if (retrying) return;
    setRetrying(true);
    setAttempt((n) => n + 1);
  }, [retrying]);

  /* Note there is no flip back to the loading state on retry: the error stays
     on screen (with the button marked busy) so the retry control — and the
     user's focus on it — survives a second failure. */
  return { runs, error, retrying, retry };
}
