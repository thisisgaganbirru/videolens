/**
 * The Content-Security-Policy and the other security headers, in one place.
 *
 * Imported by `next.config.mjs` (the web build's response headers) and by
 * `scripts/inject-csp.mjs` (the per-page `<meta>` policy written into the
 * prerendered HTML of both builds). Plain ESM with no dependencies, because
 * both of those run in Node before or after Next, never in the browser.
 *
 * Why the policy exists: the bring-your-own Gemini key sits in localStorage
 * (`infrastructure/apiKeyStore.ts`). Rendering is safe today, but if a script
 * ever runs in the page anyway (a bug, a compromised dependency, model output
 * that slips past the renderer), nothing else stops it reading the key and
 * sending it elsewhere. `connect-src` and `img-src` are what close that door:
 * fetch, XHR, beacons, WebSockets and image beacons can only reach this origin
 * and the backend. See docs/frontend/security-headers.md.
 *
 * Two layers, because Next prerenders every page and per-request nonces would
 * force dynamic rendering:
 *
 *   1. Web build: the full policy as a response header (`next.config.mjs`),
 *      with `script-src 'self' 'unsafe-inline'`, so a response Next renders
 *      at request time (never the case today) still works.
 *   2. Both builds: a `<meta>` policy in each prerendered document whose
 *      `script-src` lists the SHA-256 of every inline script in that exact
 *      file. A document is governed by every policy it carries, so on the web
 *      the effective rule is the intersection, i.e. hashes only. The
 *      Capacitor export has no server, so there the meta carries the whole
 *      policy (minus `frame-ancestors`, which a meta tag cannot set).
 */

import { createHash } from "node:crypto";

/** Must match the fallback in `infrastructure/apiBase.ts`. */
export const API_BASE_FALLBACK = "http://localhost:8000";

/** The backend's origin, from the same env var the client bundle inlines. */
export function apiOriginFrom(raw) {
  const value = raw || API_BASE_FALLBACK;
  try {
    return new URL(value).origin;
  } catch {
    throw new Error(`NEXT_PUBLIC_API_BASE_URL is not a valid URL: ${JSON.stringify(value)}`);
  }
}

/**
 * The identity provider's origin (auth phase 2), from
 * `NEXT_PUBLIC_SUPABASE_URL`, the same value the client bundle inlines and
 * `infrastructure/authSession.ts` talks to. `null` when blank: that build has
 * sign-in off (`NullAuthSession` never opens a connection), so it gets no
 * extra origin at all. Deliberately not a `https://*.supabase.co` fallback: a
 * wildcard would let a script that read the BYOK key post it to *any*
 * Supabase project, including one an attacker owns. One exact origin keeps
 * the door as narrow as the backend's. See docs/frontend/security-headers.md.
 */
export function authOriginFrom(raw) {
  const value = (raw || "").trim();
  if (!value) return null;
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`NEXT_PUBLIC_SUPABASE_URL is not a valid URL: ${JSON.stringify(value)}`);
  }
  if (url.protocol !== "https:" && url.hostname !== "localhost" && url.hostname !== "127.0.0.1") {
    throw new Error(`NEXT_PUBLIC_SUPABASE_URL must be https: ${JSON.stringify(value)}`);
  }
  return url.origin;
}

/**
 * Every directive except `script-src`, which differs per layer.
 *
 * - img-src: thumbnails are `data:` URLs, History posters are `blob:` object
 *   URLs, platform icons are same-origin files. A remote image in the
 *   model-written notes is deliberately blocked: it would be a beacon.
 * - media-src blob: UploadForm reads a picked file's duration through a
 *   `blob:` URL on a detached <video>/<audio>.
 * - style-src 'unsafe-inline': React server-renders `style=""` attributes
 *   (GFM table alignment, layout values), which a hash cannot cover without
 *   'unsafe-hashes'. Style injection cannot read the key; with img-src and
 *   font-src locked to this origin it cannot carry anything out either.
 * - font-src 'self': next/font self-hosts both faces at build time.
 * - connect-src also lists the identity provider's one origin when sign-in
 *   is configured (`authOriginFrom`); sign-in is plain fetch, no WebSocket.
 */
function baseDirectives(apiOrigin, authOrigin = null) {
  return [
    ["default-src", "'self'"],
    ["connect-src", ["'self'", apiOrigin, authOrigin].filter(Boolean).join(" ")],
    ["img-src", "'self' data: blob:"],
    ["media-src", "'self' blob:"],
    ["style-src", "'self' 'unsafe-inline'"],
    ["font-src", "'self'"],
    ["worker-src", "'self'"],
    ["manifest-src", "'self'"],
    ["frame-src", "'none'"],
    ["object-src", "'none'"],
    ["base-uri", "'self'"],
    ["form-action", "'self'"],
  ];
}

function serialize(directives) {
  return directives.map(([name, value]) => `${name} ${value}`).join("; ");
}

/**
 * The web build's header policy. `dev` adds 'unsafe-eval', which React needs
 * in development only (Next's CSP guide); production never gets it.
 */
export function headerPolicy({ apiOrigin, authOrigin = null, dev = false }) {
  const script = `'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`;
  return serialize([
    ...baseDirectives(apiOrigin, authOrigin),
    ["script-src", script],
    ["frame-ancestors", "'none'"],
  ]);
}

/** The per-document meta policy for the web build: scripts only. */
export function webMetaPolicy({ scriptHashes }) {
  return serialize([["script-src", ["'self'", ...scriptHashes].join(" ")]]);
}

/** The per-document meta policy for the Capacitor export: the whole policy. */
export function exportMetaPolicy({ apiOrigin, authOrigin = null, scriptHashes }) {
  return serialize([
    ...baseDirectives(apiOrigin, authOrigin),
    ["script-src", ["'self'", ...scriptHashes].join(" ")],
  ]);
}

/**
 * Every response header the web build sends. `authOrigin` defaults to the
 * one derived from `NEXT_PUBLIC_SUPABASE_URL`, so `next.config.mjs` needs no
 * change of its own to carry it (and the config's own watcher does not
 * restart a running dev server for it). Pass `null` to leave it out.
 */
export function securityHeaders({
  apiOrigin,
  authOrigin = authOriginFrom(process.env.NEXT_PUBLIC_SUPABASE_URL),
  dev = false,
}) {
  return [
    { key: "Content-Security-Policy", value: headerPolicy({ apiOrigin, authOrigin, dev }) },
    /* Stricter than strict-origin-when-cross-origin: the backend never reads
       Referer (CORS uses Origin), and outbound links already carry
       rel="noreferrer". Same-origin navigations keep the full referrer. */
    { key: "Referrer-Policy", value: "same-origin" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    /* Belt and braces with frame-ancestors 'none', for old browsers. */
    { key: "X-Frame-Options", value: "DENY" },
    /* One year, no includeSubDomains and no preload: the production domain's
       siblings are not this app's to pin. Browsers ignore it over plain http
       (local `next start`). */
    { key: "Strict-Transport-Security", value: "max-age=31536000" },
    /* Off: hardware and sensors the app never asks for. Left alone on
       purpose: web-share (Share notes) and clipboard-write (Copy). The file
       picker's camera option is the OS chooser, not getUserMedia, so
       camera=() does not affect uploads. */
    {
      key: "Permissions-Policy",
      value: [
        "camera=()",
        "microphone=()",
        "geolocation=()",
        "payment=()",
        "usb=()",
        "serial=()",
        "hid=()",
        "midi=()",
        "display-capture=()",
        "accelerometer=()",
        "gyroscope=()",
        "magnetometer=()",
      ].join(", "),
    },
  ];
}

/* ---- Inline-script hashing (scripts/inject-csp.mjs) ---- */

const SCRIPT_TAG = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;

/**
 * `'sha256-…'` for every inline script in a document, de-duplicated, in
 * document order. Scripts with `src` are covered by 'self' instead. The hash
 * is over the exact text between the tags, which is what the browser hashes
 * (script content is raw text: no entity decoding).
 */
export function inlineScriptHashes(html) {
  const seen = new Set();
  for (const match of html.matchAll(SCRIPT_TAG)) {
    if (/\bsrc\s*=/i.test(match[1])) continue;
    const body = match[2];
    if (body === "") continue;
    seen.add(`'sha256-${createHash("sha256").update(body, "utf8").digest("base64")}'`);
  }
  return [...seen];
}

const META_CSP = /<meta http-equiv="Content-Security-Policy"[^>]*>/gi;

/**
 * Writes the meta policy into a document, replacing one from an earlier run
 * (so the script is idempotent). It goes right after `<meta charset>` (kept
 * first, inside the first 1024 bytes) and therefore before every script.
 */
export function withMetaPolicy(html, policy) {
  const clean = html.replace(META_CSP, "");
  const tag = `<meta http-equiv="Content-Security-Policy" content="${policy.replace(/"/g, "&quot;")}"/>`;
  const charset = /<meta\s+charSet="[^"]*"\s*\/?>/i.exec(clean);
  const head = /<head\b[^>]*>/i.exec(clean);
  const anchor = charset ?? head;
  if (!anchor) throw new Error("document has no <head>");
  const at = anchor.index + anchor[0].length;
  const out = clean.slice(0, at) + tag + clean.slice(at);
  const firstScript = out.search(/<script\b/i);
  if (firstScript !== -1 && firstScript < out.indexOf(tag)) {
    throw new Error("a <script> precedes the CSP meta tag; it would run unchecked");
  }
  return out;
}
