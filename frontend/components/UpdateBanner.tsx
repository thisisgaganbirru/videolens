"use client";

import { Download } from "lucide-react";
import { useUpdateCheck } from "@/application/useUpdateCheck";

export default function UpdateBanner() {
  const { update } = useUpdateCheck();

  if (!update) return null;

  return (
    <div
      className="flex min-h-14 items-center justify-between gap-3 border-b border-[var(--color-rule)] bg-[var(--color-surface-raised)] px-[var(--page-gutter)] text-sm text-[var(--color-text)]"
      style={{ zIndex: "var(--z-banner)" }}
    >
      <span className="min-w-0 leading-5">Version {update.versionName} is available.</span>
      <a
        href={update.releaseUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="button-secondary min-h-11 shrink-0 px-3"
      >
        <Download className="h-4 w-4" aria-hidden="true" />
        <span className="hidden sm:inline">Download update</span>
        <span className="sm:hidden">Update</span>
      </a>
    </div>
  );
}
