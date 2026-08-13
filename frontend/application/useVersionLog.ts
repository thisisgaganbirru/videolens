"use client";

import { useEffect, useState } from "react";
import type { VersionLogEntry } from "@/domain/ports";
import { versionLogGateway } from "@/infrastructure/container";

export function useVersionLog() {
  const [entries, setEntries] = useState<VersionLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    versionLogGateway
      .fetchEntries()
      .then(setEntries)
      .catch(() => setError("Could not load the version log."));
  }, []);

  return { entries, error };
}
