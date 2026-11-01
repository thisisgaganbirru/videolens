"use client";

import { useEffect } from "react";
import type { PaintedTheme } from "@/domain/ports";
import { systemBarsStyler } from "@/infrastructure/container";

function paintedTheme(root: HTMLElement): PaintedTheme {
  return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

/**
 * Keeps the native status bar and gesture bar icons legible over the page.
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
    return () => observer.disconnect();
  }, []);
}
