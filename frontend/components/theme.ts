/* The light/dark preference, in one place.
 *
 * Deliberately not a hook, a context or an `application/` port: the toggle is
 * stateless by design. It flips `data-theme` on <html>, CSS does the rest, and
 * no React state exists that could disagree with the painted theme. This module
 * exists so the three places that need the same constants — the pre-paint
 * blocking script in `app/layout.tsx`, the toggle button, and the browser-chrome
 * colour — cannot drift apart.
 *
 * The native status/gesture bar icon colour is the one theme-driven side effect
 * that does need a port (it crosses into Capacitor): see
 * `application/useSystemBarsTheme.ts`, which follows `data-theme` on its own.
 */

export const THEME_STORAGE_KEY = "videolens_theme";

export type Theme = "light" | "dark";

/**
 * Nothing stored: follow the device (`prefers-color-scheme`), live — refinement
 * 2, #3. It used to be light regardless of the OS, which made the installed
 * app's launch screen (it follows the OS night mode, the only signal before the
 * WebView exists) hand off from dark to a light page. A stored "light"/"dark"
 * still wins; only the no-choice case follows the device.
 *
 * `tokens.css` still declares light on bare `:root` with no media block: the
 * pre-paint script in `app/layout.tsx` always stamps `data-theme`, resolving
 * the device preference itself, so the stylesheet has nothing to decide.
 */
export const SYSTEM_DARK_QUERY = "(prefers-color-scheme: dark)";

/** The stored explicit choice, or null when the device decides. */
export function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

/** `--color-paper` in each theme (see `app/tokens.css`) — keep them equal. */
export const THEME_COLOR: Record<Theme, string> = {
  light: "#F6F4EE",
  dark: "#0E100F",
};

/**
 * Keep the browser/OS chrome bar on the theme the page is actually painting.
 * It used to be two `<meta name="theme-color" media="(prefers-color-scheme: …)">`
 * tags, which is wrong the moment the app's theme stops tracking the OS — a
 * dark-OS first visitor now gets a light page, and would have got a dark strip
 * above it. One tag, driven by the same value that drives `data-theme`.
 */
export function syncThemeColorMeta(theme: Theme): void {
  let meta = document.querySelector('meta[name="theme-color"]');
  if (!meta) {
    meta = document.createElement("meta");
    meta.setAttribute("name", "theme-color");
    document.head.appendChild(meta);
  }
  meta.setAttribute("content", THEME_COLOR[theme]);
}
