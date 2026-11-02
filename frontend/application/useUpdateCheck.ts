"use client";

import { useCallback, useEffect, useState } from "react";
import type { UpdateInfo } from "@/domain/ports";
import { updateChecker, updateDismissalStore } from "@/infrastructure/container";

/* The native update check (docs/frontend/android-update-check.md), plus the
   banner's dismiss (refinement 9). A dismissal is remembered by versionCode:
   the banner stays hidden for that build and any older one, and shows again
   as soon as the backend reports a newer build. Read once per check, after
   the fetch, so the decision never depends on render timing. */
export function useUpdateCheck() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    void updateChecker.checkForUpdate().then((next) => {
      if (cancelled) return;
      const dismissed = updateDismissalStore.dismissedCode();
      setUpdate(next && (dismissed === null || next.versionCode > dismissed) ? next : null);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const dismiss = useCallback(() => {
    if (update) updateDismissalStore.dismiss(update.versionCode);
    setUpdate(null);
  }, [update]);

  return { update, dismiss };
}
