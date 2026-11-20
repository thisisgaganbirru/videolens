"use client";

import { useEffect } from "react";

/* UX fix spec 4.6 (2026-11-14): the tab title names the view, so a browser
   tab, the task switcher and a screen reader's page announcement say where
   you are. The suffix is the prerendered title's last " · " part (the app
   name), read once on the first effect — never during render, and never
   from localStorage.

   2026-11-20: Next writes the route's metadata title back on its own
   schedule (a query-only navigation such as `?view=history`, a metadata
   re-render), which silently undid the view's title. While mounted, a
   MutationObserver on <head> puts it back whenever something else changes
   it. Plain DOM in an effect, so the web build and the static export behave
   the same, and there is no inline script for the CSP to know about. */
let suffix: string | null = null;

export function useDocumentTitle(label: string | null): void {
  useEffect(() => {
    if (suffix === null) suffix = document.title.split(" · ").pop() ?? document.title;
    const wanted = label ? `${label} · ${suffix}` : suffix;
    /* Only on the route this was set for (2026-11-20). Leaving it, Next may
       write the next route's title before this effect's cleanup runs; a
       change of path, or a cleanup already run, means hands off, so that
       title is never put back to this view's. Query-only moves
       (`?view=history`) keep the path, and stay covered. */
    const path = window.location.pathname;
    let active = true;
    const assert = () => {
      if (!active || window.location.pathname !== path) return;
      if (document.title !== wanted) document.title = wanted;
    };
    assert();
    if (typeof MutationObserver === "undefined" || !document.head) {
      return () => {
        active = false;
      };
    }
    /* The title element's text, or the element itself swapped out. Setting
       it here is a mutation too; the equality check above ends that loop. */
    const observer = new MutationObserver(assert);
    observer.observe(document.head, { childList: true, subtree: true, characterData: true });
    return () => {
      active = false;
      observer.disconnect();
    };
  }, [label]);
}
