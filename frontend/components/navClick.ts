import type { MouseEvent } from "react";

/**
 * Anything the browser would rather handle itself than let us intercept.
 *
 * Every in-app destination (top bar, phone menu, bottom tab bar, More sheet)
 * is a real `<a href>`, so middle-click, ctrl-click and "copy link address"
 * keep working. Only a plain left-click is swapped for an in-place
 * `goToMainTab`, and only on the route that can update in place.
 */
export function isPlainLeftClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return (
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey
  );
}
