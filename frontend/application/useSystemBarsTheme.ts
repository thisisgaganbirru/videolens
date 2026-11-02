"use client";

import { useEffect } from "react";
import type { PaintedTheme } from "@/domain/ports";
import { systemBarsStyler } from "@/infrastructure/container";

function paintedTheme(root: HTMLElement): PaintedTheme {
  return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

/**
 * Keeps the native status bar and gesture bar icons legible over whatever is
 * behind them — the page on WebView 140+, the OS-themed window below that (the
 * adapter decides which; see infrastructure/systemBars.ts).
 *
 * Follows `<html data-theme>` rather than taking the theme as an argument: that
 * attribute is the single source of truth for the painted theme (stamped
 * pre-paint by the blocking script in `app/layout.tsx`, flipped by
 * `toggleTheme`), so observing it covers first launch, the toggle, and any
 * future writer without each one having to remember to call this.
 *
 * Mount once per route. `ThemeToggle` does it, and every route renders exactly
 * one via `AppNav`.
 */
export function useSystemBarsTheme(): void {
  useEffect(() => {
    const root = document.documentElement;
    let last: PaintedTheme | null = null;

    const sync = () => {
      const theme = paintedTheme(root);
      if (theme === last) return;
      last = theme;
      void systemBarsStyler.matchTheme(theme);
    };

    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });

    /* WebView < 140 (refinement 2, #2): the bars sit over the OS-themed window,
       so their style is resolved from the OS night mode, natively, once per
       call. Re-apply when that can have changed: an OS theme flip seen by the
       page, and coming back to the foreground (a flip while backgrounded). */
    if (!systemBarsStyler.followsSystemTheme()) return () => observer.disconnect();
    const reapply = () => void systemBarsStyler.matchTheme(paintedTheme(root));
    const onVisible = () => {
      if (document.visibilityState === "visible") reapply();
    };
    const scheme = window.matchMedia?.("(prefers-color-scheme: dark)");
    scheme?.addEventListener?.("change", reapply);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      observer.disconnect();
      scheme?.removeEventListener?.("change", reapply);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);
}
