"use client";

import { Moon, Sun } from "lucide-react";
import { useSystemBarsTheme } from "@/application/useSystemBarsTheme";
import { syncThemeColorMeta, THEME_STORAGE_KEY, type Theme } from "@/components/theme";

/* Reads and writes the same attribute + key the blocking script in
   app/layout.tsx sets before first paint. No React state is involved: the
   glyph swap is a CSS rule keyed off <html data-theme>, so the button can't
   disagree with the painted theme.

   With nothing stored the page follows the device (refinement 2, #3), and the
   button shows whichever theme that resolved to. Pressing it stores the
   opposite as an explicit choice, which from then on wins over the device —
   the head script's live listener checks storage before acting. */
export function toggleTheme() {
  const root = document.documentElement;
  const next: Theme = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
  root.setAttribute("data-theme", next);
  syncThemeColorMeta(next);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    /* private mode — the choice just doesn't persist */
  }
}

/* Shared by the app shell and the standalone routes so every page carries the
   same control, rather than each rebuilding a lookalike.

   Also the one mount point for the native system-bar sync: every route renders
   exactly one ThemeToggle, and the hook follows <html data-theme>, so the
   status/gesture bar icons flip with the toggle without toggleTheme knowing. */
export default function ThemeToggle() {
  useSystemBarsTheme();
  return (
    <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
      <Sun className="icon-sun" aria-hidden="true" />
      <Moon className="icon-moon" aria-hidden="true" />
    </button>
  );
}
