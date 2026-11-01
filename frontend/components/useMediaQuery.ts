"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether a CSS media query matches, kept in sync as the window resizes.
 *
 * `useSyncExternalStore` rather than state set in an effect: it subscribes to
 * the `change` event directly, so there is no extra render after mount and no
 * `react-hooks/set-state-in-effect` lint. The server snapshot is `false`
 * (this app is a static export, prerendered with no window), so callers must
 * treat `false` as the safe default — the narrow layout.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false
  );
}
