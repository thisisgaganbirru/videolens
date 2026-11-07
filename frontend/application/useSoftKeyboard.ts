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

/* The smallest gap kept at the band's bottom edge when field + message only
   just fit (or do not fit at all), so the message's last line is not flush
   against the keyboard. */
const TIGHT_MARGIN = 4;

type Span = { top: number; bottom: number };

function spanOf(elements: HTMLElement[]): Span {
  let top = Infinity;
  let bottom = -Infinity;
  for (const el of elements) {
    const r = el.getBoundingClientRect();
    top = Math.min(top, r.top);
    bottom = Math.max(bottom, r.bottom);
  }
  return { top, bottom };
}

/* The field's own error message(s): what its aria-describedby points at that
   is an error (`role="alert"` / `.field-error`) and is actually rendered.
   Informational notes it also points at (the link-capability callout) are not
   worth pushing the message off screen for. */
function errorMessages(field: HTMLElement): HTMLElement[] {
  const ids = (field.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);
  const found: HTMLElement[] = [];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (!el || !el.matches('[role="alert"], .field-error')) continue;
    if (el.getBoundingClientRect().height === 0) continue;
    found.push(el);
  }
  return found;
}

/**
 * Bring a field — and the message that belongs to it — into the part of the
 * screen the user can actually see (refinement 4, INT-01 / INT-05; refinement
 * 5, INT-01b).
 *
 * What is revealed, in order of preference:
 *   1. the field's `[data-reveal-group]` (the link form with its label, field,
 *      error and Analyze button; the terms row; the drop zone), plus its error,
 *      when all of that fits in the visible band with margins — centred;
 *   2. otherwise the field plus its error message (its aria-describedby
 *      `role="alert"`), centred when it fits;
 *   3. otherwise (a landscape phone with the keyboard up leaves ~140px) the
 *      pair is aligned so the MESSAGE's bottom edge is visible, at the cost of
 *      the field's top edge. The Analyze button is never preferred over it:
 *      landscape QA showed the field and button with the message 5px from
 *      view, because step 1 failed and the old fallback centred the field
 *      alone.
 *
 * "Visible" is the visual viewport, clipped to the field's scrolling section
 * (the installed app's header sits above it): in the installed app the WebView itself
 * shrinks for the keyboard, but a mobile browser shrinks only the visual
 * viewport, and `scrollIntoView` alone centres in the layout viewport — under
 * the keyboard. So it centres the field first (which moves every nested
 * scroller roughly into place), then measures the chosen span against the
 * visual viewport and nudges the field's nearest scroller by the difference.
 *
 * Instant, not smooth: a smooth scroll started while the keyboard is still
 * resizing the WebView can be cut short by that resize, which is one way the
 * landscape field ended up under the keyboard (INT-05).
 */
export function revealField(field: HTMLElement): void {
  const group = field.closest<HTMLElement>("[data-reveal-group]");
  const vv = window.visualViewport;
  const scroller = scrollParent(field);
  let top = Math.max(0, vv?.offsetTop ?? 0);
  let bottom = Math.min(window.innerHeight, top + (vv?.height ?? window.innerHeight));
  /* The installed app scrolls a section under a fixed header: only the part
     of the screen that section occupies is visible band. Ignoring it is how a
     landscape field ended up half under the header with its message below
     the keyboard (refinement 5, INT-01b) — the window had room, the section
     did not. */
  if (scroller && scroller !== document.scrollingElement && scroller !== document.body) {
    const clip = scroller.getBoundingClientRect();
    top = Math.max(top, clip.top);
    bottom = Math.min(bottom, clip.bottom);
  }
  const band = bottom - top;
  const messages = errorMessages(field);
  const pair = [field, ...messages];
  const height = (span: Span) => span.bottom - span.top;
  const roomy = (span: Span) => height(span) <= band - 2 * REVEAL_MARGIN;
  const parts = group && roomy(spanOf([group, ...messages])) ? [group, ...messages] : pair;
  const inView = (span: Span) => span.top >= top + REVEAL_MARGIN && span.bottom <= bottom - REVEAL_MARGIN;
  /* Already fully visible: leave the page where the user put it. */
  if (inView(spanOf(parts))) return;
  field.scrollIntoView({ block: "center", inline: "nearest" });

  const span = spanOf(parts);
  let delta: number;
  if (roomy(span)) {
    /* Centre the whole span (scrollIntoView centred the field, not the pair). */
    delta = (span.top + span.bottom) / 2 - (top + bottom) / 2;
  } else {
    /* Too tall for the band: the message's bottom edge wins. */
    const edge = Math.max(TIGHT_MARGIN, Math.min(REVEAL_MARGIN, (band - height(span)) / 2));
    delta = span.bottom - (bottom - edge);
  }
  if (Math.abs(delta) < 1) return;
  scroller?.scrollBy({ top: delta });
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
