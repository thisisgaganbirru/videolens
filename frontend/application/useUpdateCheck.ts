"use client";

import { useEffect, useState } from "react";
import type { UpdateInfo } from "@/domain/ports";
import { updateChecker } from "@/infrastructure/container";

export function useUpdateCheck() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);

  useEffect(() => {
    updateChecker.checkForUpdate().then(setUpdate);
  }, []);

  return { update };
}
