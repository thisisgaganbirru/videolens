"use client";

import { useEffect, useState } from "react";
import { apiKeyStore } from "@/infrastructure/container";

/**
 * The bring-your-own-key field's state.
 *
 * - `value`  what is in the field right now
 * - `stored` what is actually in localStorage (trimmed, "" when none), so the
 *            panel can tell "saved" from "typed but not saved yet"
 * - `saved`  true right after a Save or Remove, until the field is edited —
 *            the cue for the one-line confirmation
 */
export function useGeminiApiKey() {
  /* One state object, so the post-hydration read below is a single setState.
     Reading localStorage after mount (not during render) is what keeps the
     static export's prerendered HTML and the first client render identical. */
  const [state, setState] = useState({ value: "", stored: "", saved: false });

  useEffect(() => {
    const stored = apiKeyStore.get();
    setState({ value: stored, stored, saved: false });
  }, []);

  const update = (next: string) => {
    setState((current) => ({ ...current, value: next, saved: false }));
  };

  const save = () => {
    apiKeyStore.set(state.value);
    const stored = apiKeyStore.get();
    setState({ value: stored, stored, saved: true });
  };

  const clear = () => {
    apiKeyStore.set("");
    setState({ value: "", stored: "", saved: true });
  };

  return { value: state.value, stored: state.stored, saved: state.saved, update, save, clear };
}
