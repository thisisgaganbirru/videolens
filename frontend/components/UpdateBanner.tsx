"use client";

import { Download } from "lucide-react";
import { useUpdateCheck } from "@/application/useUpdateCheck";

/* No drawn spec for this either — ported by analogy to the terminal shell's
   own bands: flat --color-paper-2, a single hairline below it, square corners,
   no shadow. It sits directly inside .viewport above the shell, so it must not
   flex-shrink or the one-viewport frame below it loses its measured height. */

export default function UpdateBanner() {
  const { update } = useUpdateCheck();

  if (!update) return null;

  return (
    <div
      className="flex min-h-14 shrink-0 items-center justify-between gap-[var(--space-xs)] border-b border-[var(--color-rule)] bg-[var(--color-paper-2)] px-[var(--page-gutter)] text-[0.78rem] text-[var(--color-ink-2)]"
      style={{ zIndex: "var(--z-banner)" }}
    >
      <span className="min-w-0 leading-5">Version {update.versionName} is available.</span>
      <a
        href={update.releaseUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="btn btn-secondary min-h-11 shrink-0"
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="hidden sm:inline">download update</span>
        <span className="sm:hidden">update</span>
      </a>
    </div>
  );
}
