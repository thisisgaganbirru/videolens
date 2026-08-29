"use client";

import { useCallback, useEffect, useState } from "react";
import type { VersionLogEntry } from "@/domain/ports";
import { versionLogGateway } from "@/infrastructure/container";

export function useVersionLog() {
  const [entries, setEntries] = useState<VersionLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  /* Same mechanism as useRunHistory: bumping this re-runs the effect, so retry
     travels the exact code path the mount already uses rather than a second
     async callback that has to be kept in step with it. */
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    versionLogGateway
      .fetchEntries()
      .then((next) => {
        if (cancelled) return;
        setEntries(next);
        setError(null);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load the version log.");
      })
      .finally(() => {
        if (!cancelled) setRetrying(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => {
    /* Guarded here rather than by disabling the button: a focused element that
       becomes `disabled` is blurred to <body>, so a keyboard user who presses
       Try again loses their place. The button stays focusable and marks itself
       `aria-disabled` while a request is in flight. The guard reads state
       directly instead of living inside a setState updater — updaters must be
       pure, and StrictMode double-invokes them in dev. */
    if (retrying) return;
    setRetrying(true);
    setAttempt((n) => n + 1);
  }, [retrying]);

  /* No flip back to the loading note on retry: the error stays on screen with
     the button marked busy, so the control the user is standing on survives a
     second failure. */
  return { entries, error, retrying, retry };
}
