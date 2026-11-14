"use client";

import { useEffect } from "react";

/* UX fix spec 4.6 (2026-11-14): the tab title names the view, so a browser
   tab, the task switcher and a screen reader's page announcement say where
   you are. The suffix is the prerendered title's last " · " part (the app
   name), read once on the first effect — never during render, and never
   from localStorage. */
let suffix: string | null = null;

export function useDocumentTitle(label: string | null): void {
  useEffect(() => {
    if (suffix === null) suffix = document.title.split(" · ").pop() ?? document.title;
    document.title = label ? `${label} · ${suffix}` : suffix;
  }, [label]);
}
