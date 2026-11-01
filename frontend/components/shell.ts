/* Which chrome this display mode gets, in one place.
 *
 * `web`  — a normal browser tab (phone or desktop): top bar, phone menu, footer.
 * `app`  — installed: standalone PWA or the Capacitor Android build: top bar
 *          (brand + theme), bottom tab bar, More sheet, no footer.
 *
 * Decided by the blocking pre-paint script in `app/layout.tsx`, which stamps
 * `<html data-shell>`; both variants are always rendered and CSS shows one.
 * Never decided in React state: every route is prerendered, so a state-picked
 * nav would paint the wrong chrome first and mismatch on hydration.
 */

export type ShellMode = "web" | "app";

/**
 * Testing override. `localStorage.videolens_shell = "app"` (or `"web"`) forces
 * a mode in an ordinary browser tab, so the installed-app chrome can be checked
 * without installing anything. Remove the key to go back to detection.
 */
export const SHELL_STORAGE_KEY = "videolens_shell";
