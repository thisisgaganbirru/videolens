"use client";

import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { checkForUpdate, type UpdateInfo } from "@/lib/updateCheck";

export default function UpdateBanner() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);

  useEffect(() => {
    checkForUpdate().then(setUpdate);
  }, []);

  if (!update) return null;

  return (
    <div className="flex items-center justify-between gap-3 border-b border-[#292e2b] bg-[#121513] px-4 py-2 text-sm text-slate-300">
      <span className="min-w-0 truncate">A new version ({update.versionName}) is available.</span>
      <a
        href={update.releaseUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[#343a36] px-3 py-1.5 font-medium text-slate-100 transition-colors hover:bg-[#1b201d] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
      >
        <Download className="h-4 w-4" aria-hidden="true" />
        Download update
      </a>
    </div>
  );
}
