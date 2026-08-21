"use client";

import { useEffect, useState } from "react";
import { sharedUrlSource } from "@/infrastructure/container";

/** One delivered share. `receivedAt` makes every arrival a distinct object, so
 *  sharing the *same* link twice still reaches the effects downstream. */
export type SharedUrl = {
  url: string;
  receivedAt: number;
};

/**
 * The most recent URL shared into the app from outside it.
 *
 * This lives in `application/` rather than in the intake component because a
 * share has to be handled whatever is on screen. It used to be a `useEffect`
 * inside `UploadForm`, which is mounted only while the run state is idle — so a
 * link shared while a finished result was up arrived with no listener, sat in
 * localStorage, and surfaced later as a stale prefill once the user pressed
 * back. `HomeScreen` is always mounted; it isn't.
 */
export function useSharedUrl(): SharedUrl | null {
  const [shared, setShared] = useState<SharedUrl | null>(null);

  useEffect(() => {
    const consume = () => {
      const url = sharedUrlSource.take();
      if (url) setShared({ url, receivedAt: Date.now() });
    };

    /* Once for a share that launched the app (it is already waiting), then on
       every share that arrives while it is open. */
    consume();
    return sharedUrlSource.subscribe(consume);
  }, []);

  return shared;
}
