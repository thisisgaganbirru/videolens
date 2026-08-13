"use client";

import { useEffect, useState } from "react";
import type { RunSummary } from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import { runsGateway } from "@/infrastructure/container";

export function useRunHistory() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    runsGateway
      .listRuns()
      .then((response) => setRuns(response.runs))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load history."));
  }, []);

  return { runs, error };
}
