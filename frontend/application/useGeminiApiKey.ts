"use client";

import { useEffect, useState } from "react";
import { apiKeyStore } from "@/infrastructure/container";

export function useGeminiApiKey() {
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setValue(apiKeyStore.get());
  }, []);

  const update = (next: string) => {
    setValue(next);
    setSaved(false);
  };

  const save = () => {
    apiKeyStore.set(value);
    setSaved(true);
  };

  const clear = () => {
    setValue("");
    apiKeyStore.set("");
    setSaved(true);
  };

  return { value, saved, update, save, clear };
}
