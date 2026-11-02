/* VideoLens service worker — TEMPLATE.
 *
 * This is the source. The served file is GENERATED from it by
 * `scripts/build-sw.mjs` after every `next build`, which substitutes the two
 * `__PLACEHOLDER__` tokens below and writes `public/sw.js` (served by
 * `next start`) and `out/sw.js` (the Capacitor static export).
 *
 * Edit this file. Never edit `public/sw.js` — it is a build artifact and is
 * gitignored.
 */

/* Generated: a digest of everything precached below. It changes whenever the
 * precached set does — in practice every build, since Next's random buildId is
 * a path segment in three of the assets — which is what makes a deploy
 * invalidate the old cache instead of leaving a stale shell paired with chunks
 * that no longer exist. It also changes the bytes of this file, which is the
 * only signal the browser uses to decide a worker needs re-installing. That is
 * precisely what the old hand-written `videolens-shell-v1` never did. */
const CACHE_NAME = "__CACHE_NAME__";

/* The documents that have to be readable with no network. `/` is the landing
 * page and `/app` the tool since Phase 5c. */
const SHELL_DOCUMENTS = ["/", "/app", "/offline", "/privacy", "/terms"];

const STATIC_ASSETS = ["/icon-192.png", "/icon-512.png"];

/* Generated: every hashed JS/CSS file the client bundle loads. These CANNOT be
 * hand-listed — Next content-hashes the filenames, so any literal here would be
 * correct for exactly one build and silently wrong after the next one. Without
 * them React never hydrates offline and every client control (the theme toggle,
 * the nav drawer, the tab links) renders but does nothing. */
const BUILD_ASSETS = __BUILD_ASSETS__;

const PRECACHE = [...SHELL_DOCUMENTS, ...STATIC_ASSETS, ...BUILD_ASSETS];

/* ---- Offline navigation policy -------------------------------------------
 *
 * An ALLOWLIST, deliberately, so that a route added later falls into the safe
 * bucket (/offline) rather than silently into the wrong one.
 *
 * A route earns a place here only if it is genuinely complete with no network:
 * every word of it is in the cached HTML and it calls no API. Both legal
 * documents qualify — they are static text, they are already precached, and
 * hiding them behind an offline screen is a pure loss.
 *
 * `/` qualifies too since Phase 5c: it is the landing page now, static text
 * with no API call. It is also what answers the legacy `/?view=history`
 * offline — its inline redirect script (application/landingRedirect.ts) needs
 * no bundle and sends the browser on to `/app?view=history`, which the view
 * rule below serves from the cache. Every other legacy `/?view=…` hops the
 * same way and lands on /offline, as it did before.
 *
 * Bare `/app` (Analyze) is deliberately NOT here, and this is the whole product
 * call — `/app?view=history` is, via OFFLINE_CAPABLE_VIEWS below. The tool is
 * useless without the API: serving the cached shell would give an upload form
 * that cannot upload. That is a worse lie than "you are offline", and it would
 * make the offline page's own `Try again` button load a half-working app
 * instead of staying put.
 */
const OFFLINE_CAPABLE_DOCUMENTS = ["/", "/privacy", "/terms"];
const OFFLINE_FALLBACK = "/offline";

/* Phase 5a: History lives in this browser (IndexedDB), so the History view is
 * genuinely complete with no network — its list, its posters and every
 * finished run's result are all on the device. It is the one app address
 * served from the cached shell (`/app` since Phase 5c, whose client code reads
 * `?view=` after hydrating). Every other view of `/app` still needs the API
 * and still gets the offline page. Like the list above, an allowlist: a new view stays on the
 * safe side until someone decides otherwise. */
const OFFLINE_CAPABLE_VIEWS = ["history"];

const APP_DOCUMENT = "/app";

function cachedAppView(route, requestUrl) {
  if (route !== APP_DOCUMENT) return null;
  const view = requestUrl.searchParams.get("view");
  return view && OFFLINE_CAPABLE_VIEWS.includes(view) ? APP_DOCUMENT : null;
}

/* One route can arrive as `/privacy`, `/privacy/` or `/privacy.html` depending
 * on whether the caller is `next start`, the static export or a deep link. All
 * three are the same document and must classify the same way. */
function documentRoute(pathname) {
  let route = pathname.replace(/\.html$/, "");
  if (route.length > 1 && route.endsWith("/")) route = route.slice(0, -1);
  return route === "" ? "/" : route;
}

self.addEventListener("install", (event) => {
  /* addAll is atomic on purpose: if any one entry 404s the install fails
   * loudly and the old worker stays in charge. A per-entry allSettled would
   * leave a partial precache that looks like it works right up until the one
   * missing chunk is needed. */
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

async function respondToNavigation(request, requestUrl) {
  try {
    return await fetch(request);
  } catch {
    const route = documentRoute(requestUrl.pathname);
    if (OFFLINE_CAPABLE_DOCUMENTS.includes(route)) {
      const cached = await caches.match(route);
      if (cached) return cached;
    }
    const shell = cachedAppView(route, requestUrl);
    if (shell) {
      const cached = await caches.match(shell);
      if (cached) return cached;
    }
    const fallback = await caches.match(OFFLINE_FALLBACK);
    return fallback ?? Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const requestUrl = new URL(event.request.url);
  if (requestUrl.pathname.startsWith("/api/") || event.request.method !== "GET") return;
  if (requestUrl.origin !== self.location.origin) return;

  if (event.request.mode === "navigate") {
    event.respondWith(respondToNavigation(event.request, requestUrl));
    return;
  }

  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});
