"use client";

import { useEffect, useState } from "react";
import type { LibraryEntry } from "@/domain/entities";
import { classifyGatewayError, type GatewayError } from "@/application/gatewayError";
import { libraryGateway } from "@/infrastructure/container";

const UNKNOWN_FALLBACK = "Your library could not be searched.";
const DEBOUNCE_MS = 250;
export const PAGE_SIZE = 20;

/**
 * Search over everything the caller has analyzed.
 *
 * Same endpoint for everyone: an anonymous caller gets a title match over
 * their recent history, a workspace with durable storage gets full-text
 * search over every run. The hook does not know which — the shape is
 * identical, and that is the point of the backend's single endpoint.
 *
 * The query is debounced so typing does not fire a request per keystroke;
 * platform and page changes fire immediately, they are clicks. `runs` stays
 * `null` only before the first answer, so a later search that returns
 * nothing renders "no matches" rather than "loading".
 */
export function useLibrary() {
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [debounced, setDebounced] = useState("");
  const [runs, setRuns] = useState<LibraryEntry[] | null>(null);
  const [error, setError] = useState<GatewayError | null>(null);
  /* The request the last answer belongs to. `loading` is derived — "the
     answer on screen is not for the parameters on screen" — rather than set
     at the top of the effect, which React's lint rightly flags as a cascade. */
  const [answered, setAnswered] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(query.trim()), DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [query]);

  const request = JSON.stringify([debounced, platform, page, attempt]);

  useEffect(() => {
    let cancelled = false;
    libraryGateway
      .search({ query: debounced, platform, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
      .then((response) => {
        if (cancelled) return;
        setRuns(response.runs);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(classifyGatewayError(err, UNKNOWN_FALLBACK));
      })
      .finally(() => {
        if (!cancelled) setAnswered(request);
      });
    return () => {
      cancelled = true;
    };
  }, [debounced, platform, page, attempt, request]);

  const loading = answered !== request;

  const search = (next: string) => {
    setQuery(next);
    setPage(0);
  };

  const filterPlatform = (next: string | null) => {
    setPlatform(next);
    setPage(0);
  };

  const retry = () => setAttempt((n) => n + 1);

  return {
    query,
    search,
    platform,
    filterPlatform,
    page,
    setPage,
    runs,
    error,
    loading,
    retry,
    hasMore: (runs?.length ?? 0) >= PAGE_SIZE,
  };
}
