"use client";

import { useEffect } from "react";

/* Refinement 1, #2: with the on-screen keyboard up, the installed app's tab
   bar rode on top of it and covered the field being typed into.

   There is no keyboard plugin (@capacitor/keyboard is not installed, and this
   pass adds no native plugins), so the keyboard is inferred:

   - open: a text-entry control has focus on a coarse pointer (a touch device
     — a desktop's physical keyboard never shows anything on screen);
   - closed: focus leaves it, OR the viewport, having shrunk while it was
     focused, grows back. The second case is the Android back gesture/button
     that drops the keyboard but leaves focus in the field. Capacitor's
     SystemBars pads the WebView by the IME inset, so `innerHeight` shrinks
     there; mobile browsers shrink `visualViewport` instead. Either counts.

   The hook only stamps `<html data-keyboard="open">`; globals.css hides the
   dock under that attribute (in the app shell only). On open it also brings
   the field (with its message, see `revealField`) into the visible band —
   once after a short settle, and again the moment the shrink is actually
   measured, because on a slow WebView the keyboard's resize can land after
   the settle timer (refinement 4, INT-05). */

const TEXT_INPUT_TYPES = new Set(["text", "url", "email", "search", "password", "tel", "number", ""]);
/* Below this a height change is browser chrome (URL bar) settling, not a
   keyboard. */
const KEYBOARD_MIN_PX = 120;

function isTextEntry(el: Element | null): el is HTMLElement {
  if (!el || !(el instanceof HTMLElement)) return false;
  if (el.isContentEditable) return true;
  if (el instanceof HTMLTextAreaElement) return !el.readOnly && !el.disabled;
  if (el instanceof HTMLInputElement) {
    return TEXT_INPUT_TYPES.has(el.type) && !el.readOnly && !el.disabled;
  }
  return false;
}

function viewportHeight(): number {
  return Math.min(window.innerHeight, window.visualViewport?.height ?? window.innerHeight);
}

/* Room left clear above and below a revealed field, so it does not sit flush
   against the keyboard or the top edge. */
const REVEAL_MARGIN = 16;

function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let node = el.parentElement; node; node = node.parentElement) {
    const { overflowY } = getComputedStyle(node);
    if ((overflowY === "auto" || overflowY === "scroll") && node.scrollHeight > node.clientHeight) return node;
  }
  return (document.scrollingElement as HTMLElement | null) ?? null;
}

/**
 * Bring a field — and the message that belongs to it — into the part of the
 * screen the user can actually see (refinement 4, INT-01 / INT-05).
 *
 * The unit is the field's `[data-reveal-group]` ancestor (the link form, the
 * terms row with its error, the drop zone with its error) when that fits in
 * the visible band, else the field alone. "Visible" is the visual viewport:
 * in the installed app the WebView itself shrinks for the keyboard, but a
 * mobile browser shrinks only the visual viewport, and `scrollIntoView` alone
 * centres in the layout viewport — under the keyboard. So it centres first,
 * then measures against the visual viewport and nudges the nearest scroller
 * by whatever is still hidden.
 *
 * Instant, not smooth: a smooth scroll started while the keyboard is still
 * resizing the WebView can be cut short by that resize, which is one way the
 * landscape field ended up under the keyboard (INT-05).
 */
export function revealField(field: HTMLElement): void {
  const group = field.closest<HTMLElement>("[data-reveal-group]");
  const vv = window.visualViewport;
  const top = Math.max(0, vv?.offsetTop ?? 0);
  const bottom = Math.min(window.innerHeight, top + (vv?.height ?? window.innerHeight));
  const room = bottom - top - 2 * REVEAL_MARGIN;
  const target = group && group.getBoundingClientRect().height <= room ? group : field;
  const inView = (r: DOMRect) => r.top >= top + REVEAL_MARGIN && r.bottom <= bottom - REVEAL_MARGIN;
  /* Already fully visible: leave the page where the user put it. */
  if (inView(target.getBoundingClientRect())) return;
  target.scrollIntoView({ block: "center", inline: "nearest" });

  const rect = target.getBoundingClientRect();
  let delta = 0;
  if (rect.bottom > bottom - REVEAL_MARGIN) delta = rect.bottom - (bottom - REVEAL_MARGIN);
  if (rect.top - delta < top + REVEAL_MARGIN) delta = rect.top - (top + REVEAL_MARGIN);
  if (Math.abs(delta) < 1) return;
  scrollParent(target)?.scrollBy({ top: delta });
}

export function useSoftKeyboard(): void {
  useEffect(() => {
    const root = document.documentElement;
    if (!window.matchMedia?.("(pointer: coarse)").matches) return;

    let baseline = viewportHeight();
    let shrunk = false;
    let settleTimer = 0;

    const setOpen = (open: boolean) => {
      if (open) root.setAttribute("data-keyboard", "open");
      else root.removeAttribute("data-keyboard");
    };

    const onFocusIn = (event: FocusEvent) => {
      if (!isTextEntry(event.target as Element)) return;
      if (!root.hasAttribute("data-keyboard")) baseline = viewportHeight();
      shrunk = false;
      setOpen(true);
      const field = event.target as HTMLElement;
      window.clearTimeout(settleTimer);
      /* After the keyboard's resize, so "centre" means the visible band. */
      settleTimer = window.setTimeout(() => {
        if (document.activeElement === field) revealField(field);
      }, 300);
    };

    const onFocusOut = () => {
      /* Focus moving straight to another field fires focusin next; let it. */
      window.setTimeout(() => {
        if (!isTextEntry(document.activeElement)) {
          shrunk = false;
          setOpen(false);
        }
      }, 0);
    };

    const onResize = () => {
      const height = viewportHeight();
      if (!root.hasAttribute("data-keyboard")) {
        /* The keyboard came back over a field that never lost focus (tap the
           field again after dismissing it with back): no focusin fires, but
           the viewport shrinks. */
        const field = document.activeElement;
        if (isTextEntry(field) && baseline - height > KEYBOARD_MIN_PX) {
          shrunk = true;
          setOpen(true);
          window.requestAnimationFrame(() => {
            if (document.activeElement === field) revealField(field);
          });
          return;
        }
        baseline = height;
        return;
      }
      if (baseline - height > KEYBOARD_MIN_PX) {
        /* The keyboard's room has just been taken (or changed size, e.g. a
           suggestion strip appearing): keep the focused field in view. */
        const field = document.activeElement;
        shrunk = true;
        if (isTextEntry(field)) {
          const lastHeight = height;
          window.requestAnimationFrame(() => {
            if (document.activeElement === field && viewportHeight() === lastHeight) revealField(field);
          });
        }
      } else if (shrunk) {
        /* Grew back with focus still in the field: keyboard dismissed. */
        shrunk = false;
        setOpen(false);
      }
    };

    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    window.addEventListener("resize", onResize);
    window.visualViewport?.addEventListener("resize", onResize);
    return () => {
      window.clearTimeout(settleTimer);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      window.removeEventListener("resize", onResize);
      window.visualViewport?.removeEventListener("resize", onResize);
      root.removeAttribute("data-keyboard");
    };
  }, []);
}
