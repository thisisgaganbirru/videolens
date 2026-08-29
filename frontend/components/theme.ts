/* The light/dark preference, in one place.
 *
 * Deliberately not a hook, a context or an `application/` port: the toggle is
 * stateless by design. It flips `data-theme` on <html>, CSS does the rest, and
 * no React state exists that could disagree with the painted theme. This module
 * exists so the three places that need the same constants — the pre-paint
 * blocking script in `app/layout.tsx`, the toggle button, and the browser-chrome
 * colour — cannot drift apart.
 */

export const THEME_STORAGE_KEY = "videolens_theme";

export type Theme = "light" | "dark";

/**
 * First visit, nothing stored: **light**, regardless of `prefers-color-scheme`.
 * A product decision, not an oversight — a stored choice still wins, this only
 * covers the no-preference case. `tokens.css` already declares light on bare
 * `:root` and carries no `@media (prefers-color-scheme: dark)` block, so the
 * stylesheet and the script agree on the default with nothing to fight over.
 */
export const DEFAULT_THEME: Theme = "light";

/** sRGB equivalents of `--color-paper` in each theme (see `app/tokens.css`). */
export const THEME_COLOR: Record<Theme, string> = {
  light: "#f8fbf7",
  dark: "#0c0f0c",
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
