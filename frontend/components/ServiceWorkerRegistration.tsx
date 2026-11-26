"use client";

import { useEffect } from "react";

/* Must match the cache name prefix scripts/build-sw.mjs writes into sw.js. */
const SHELL_CACHE_PREFIX = "videolens-shell-";

export default function ServiceWorkerRegistration() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;

    if (process.env.NODE_ENV === "production") {
      void navigator.serviceWorker.register("/sw.js");
      return;
    }

    /* Dev never registers a worker, but one left by a production build on the
     * same origin keeps controlling the page and serves stale cached chunks
     * cache-first. Remove it and its shell caches so dev runs current code. */
    void navigator.serviceWorker
      .getRegistrations()
      .then((registrations) => Promise.all(registrations.map((r) => r.unregister())));
    if ("caches" in window) {
      void caches
        .keys()
        .then((keys) =>
          Promise.all(
            keys.filter((key) => key.startsWith(SHELL_CACHE_PREFIX)).map((key) => caches.delete(key)),
          ),
        );
    }
  }, []);

  return null;
}
