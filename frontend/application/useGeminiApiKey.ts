"use client";

import { useState, useSyncExternalStore } from "react";
import { apiKeyStore } from "@/infrastructure/container";

/* The stored key, read through the store's own subscription (2026-11-20), so
   a key saved or removed in another tab, or by anything else in this one, is
   what the page shows. The server snapshot is "": nothing is read from
   localStorage during the prerender or hydration, and the client value
   follows right after, which keeps the static export's HTML and the first
   client render identical. */
const subscribeKey = (onChange: () => void) => apiKeyStore.subscribe(onChange);
const readKey = () => apiKeyStore.get();
const noKey = () => "";

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
  const stored = useSyncExternalStore(subscribeKey, readKey, noKey);
  /* What was typed since the last Save or Remove; null follows `stored`. */
  const [draft, setDraft] = useState<{ value: string | null; saved: boolean }>({ value: null, saved: false });
  const value = draft.value ?? stored;

  const update = (next: string) => {
    setDraft({ value: next, saved: false });
  };

  const save = () => {
    apiKeyStore.set(value);
    setDraft({ value: null, saved: true });
  };

  const clear = () => {
    apiKeyStore.set("");
    setDraft({ value: null, saved: true });
  };

  return { value, stored, saved: draft.saved, update, save, clear };
}
