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
   the field to the middle of the band once the resize has landed. */

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
        if (document.activeElement === field) field.scrollIntoView({ block: "center", behavior: "smooth" });
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
        if (isTextEntry(document.activeElement) && baseline - height > KEYBOARD_MIN_PX) {
          shrunk = true;
          setOpen(true);
          return;
        }
        baseline = height;
        return;
      }
      if (baseline - height > KEYBOARD_MIN_PX) {
        shrunk = true;
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
