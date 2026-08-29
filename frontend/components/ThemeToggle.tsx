"use client";

import { Moon, Sun } from "lucide-react";
import { syncThemeColorMeta, THEME_STORAGE_KEY, type Theme } from "@/components/theme";

/* Reads and writes the same attribute + key the blocking script in
   app/layout.tsx sets before first paint. No React state is involved: the
   glyph swap is a CSS rule keyed off <html data-theme>, so the button can't
   disagree with the painted theme. */
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
   same control, rather than each rebuilding a lookalike. */
export default function ThemeToggle() {
  return (
    <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
      <Sun className="icon-sun" aria-hidden="true" />
      <Moon className="icon-moon" aria-hidden="true" />
    </button>
  );
}
