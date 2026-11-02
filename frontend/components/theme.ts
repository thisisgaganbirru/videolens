/* The light/dark preference, in one place.
 *
 * Deliberately not a hook, a context or an `application/` port: the toggle is
 * stateless by design. It flips `data-theme` on <html>, CSS does the rest, and
 * no React state exists that could disagree with the painted theme. This module
 * exists so the three places that need the same constants — the pre-paint
 * blocking script in `app/layout.tsx`, the toggle button, and the browser-chrome
 * colour — cannot drift apart.
 *
 * The native status/gesture bar icon colour, and since refinement 5 the native
 * night mode itself, are the theme-driven side effects that do need a port
 * (they cross into Capacitor): see `application/useSystemBarsTheme.ts`, which
 * follows `data-theme` on its own and the choice via `themePreferenceSource`.
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

/**
 * What the user chose, as the More sheet's three-way control shows it
 * (refinement 4, THM-01): "system" is the absence of a stored theme.
 */
export type ThemePreference = Theme | "system";

export function themePreference(): ThemePreference {
  return storedTheme() ?? "system";
}

/** The theme the device asks for right now. Light when it cannot be read. */
export function deviceTheme(): Theme {
  try {
    return window.matchMedia(SYSTEM_DARK_QUERY).matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** Paint `theme` now: the attribute CSS keys off, and the chrome colour. */
export function paintTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  syncThemeColorMeta(theme);
}

/**
 * Apply and remember a preference. "system" removes the stored theme, which
 * is all it takes to hand control back to the device: the head script's
 * `prefers-color-scheme` listener (app/layout.tsx) re-reads storage on every
 * change and acts only while nothing is stored. Nothing in that script changes
 * for this, which is the point — one rule ("stored wins, else the device"),
 * written once, read by both.
 */
export function setThemePreference(preference: ThemePreference): void {
  try {
    if (preference === "system") localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    /* private mode: applied for this visit, not remembered */
  }
  /* Before painting, on purpose: the native mirror's bridge call must reach
     the native side ahead of the system-bar restyle that the paint triggers
     (useSystemBarsTheme observes data-theme), so a DEFAULT bar style resolves
     against the new night mode, not the old one. */
  preferenceListeners.forEach((listener) => listener(preference));
  paintTheme(preference === "system" ? deviceTheme() : preference);
}

/* Refinement 5, THM-01b: the installed app mirrors the choice natively so the
   next launch (launch screen, window, system bars) starts on it. This module
   stays free of Capacitor: it only announces changes; the hook that owns the
   native side (application/useSystemBarsTheme.ts) listens. */
const preferenceListeners = new Set<(preference: ThemePreference) => void>();

/** What the native theme sync needs from here: read, follow, and re-resolve. */
export const themePreferenceSource = {
  read: themePreference,
  subscribe(listener: (preference: ThemePreference) => void): () => void {
    preferenceListeners.add(listener);
    return () => {
      preferenceListeners.delete(listener);
    };
  },
  /** Repaint from the device when nothing is stored. After the native night
   *  mode changes, the WebView's prefers-color-scheme can be the last to know;
   *  the head script's listener catches its change event, this is the same
   *  rule applied once more in case no event comes. */
  followDevice(): void {
    if (storedTheme() === null) paintTheme(deviceTheme());
  },
};

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
