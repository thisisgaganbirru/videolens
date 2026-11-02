"use client";

import { Moon, Sun } from "lucide-react";
import { useSystemBarsTheme } from "@/application/useSystemBarsTheme";
import { setThemePreference, themePreferenceSource, type Theme } from "@/components/theme";

/* Reads and writes the same attribute + key the blocking script in
   app/layout.tsx sets before first paint. No React state is involved: the
   glyph swap is a CSS rule keyed off <html data-theme>, so the button can't
   disagree with the painted theme.

   With nothing stored the page follows the device (refinement 2, #3), and the
   button shows whichever theme that resolved to. Pressing it stores the
   opposite as an explicit choice, which from then on wins over the device —
   the head script's live listener checks storage before acting. The way back
   to following the device is the More sheet's System option (refinement 4,
   THM-01); this button stays two-way on purpose. */
export function toggleTheme() {
  const next: Theme = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  setThemePreference(next);
}

/* Shared by the app shell and the standalone routes so every page carries the
   same control, rather than each rebuilding a lookalike.

   Also the one mount point for the native system-bar sync: every route renders
   exactly one ThemeToggle, and the hook follows <html data-theme>, so the
   status/gesture bar icons flip with the toggle without toggleTheme knowing.
   It also mirrors the choice natively (refinement 5), via the source object. */
export default function ThemeToggle() {
  useSystemBarsTheme(themePreferenceSource);
  return (
    <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
      <Sun className="icon-sun" aria-hidden="true" />
      <Moon className="icon-moon" aria-hidden="true" />
    </button>
  );
}
