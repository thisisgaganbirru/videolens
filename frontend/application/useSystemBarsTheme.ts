"use client";

import { useEffect } from "react";
import type { PaintedTheme, ThemeChoice } from "@/domain/ports";
import { nativeThemeMirror, systemBarsStyler } from "@/infrastructure/container";

/** The user's theme choice, as the caller (components/theme.ts) holds it.
 *  Passed in so this layer does not import presentation code. */
export type ThemePreferenceSource = {
  read(): ThemeChoice;
  subscribe(listener: (choice: ThemeChoice) => void): () => void;
  /** Repaint from the device if nothing is stored. */
  followDevice(): void;
};

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
 * Also mirrors the theme CHOICE (System / Light / Dark) into the native shell
 * (refinement 5, THM-01b), so the next launch's launch screen, window and bars
 * start on the app's choice rather than the OS night mode: once on mount (picks
 * up a choice made before the mirror existed, and is a native no-op when it
 * already matches) and on every change. When the native night mode actually
 * changed, DEFAULT-styled bars are re-resolved against it, and a "system"
 * choice is repainted from the device once the WebView has caught up.
 *
 * Mount once per route. `ThemeToggle` does it, and every route renders exactly
 * one via `AppNav`.
 */
export function useSystemBarsTheme(preference: ThemePreferenceSource): void {
  const { read, subscribe, followDevice } = preference;
  useEffect(() => {
    const mirror = (choice: ThemeChoice) => {
      void nativeThemeMirror.setPreference(choice).then((changed) => {
        if (!changed) return;
        if (systemBarsStyler.followsSystemTheme()) {
          void systemBarsStyler.matchTheme(paintedTheme(document.documentElement));
        }
        if (choice === "system") followDevice();
      });
    };
    mirror(read());
    return subscribe(mirror);
  }, [read, subscribe, followDevice]);

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

    /* WebView < 140 (refinement 2, #2): the bars sit over the native window,
       so their style is resolved from the native night mode, natively, once
       per call (since refinement 5 that is the app's choice, falling back to
       the OS for "system"). Re-apply when that can have changed: an OS theme flip seen by the
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
