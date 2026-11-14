# Security headers, CSP and Android backups

Protects the bring-your-own Gemini key (`localStorage` key
`videolens-gemini-api-key`, see `byok-api-key.md`) from being carried off the
page if a script ever runs in it, and keeps it out of Android backups.

Before 2026-11-07 the live site sent no Content-Security-Policy and no
security headers at all, and the APK's WebView storage went into every
backup and device transfer.

**Files**
- `frontend/security/csp.mjs` — the one source of the policy: directives,
  the security header list, inline-script hashing, meta insertion. Plain ESM,
  no dependencies, imported by the two files below.
- `frontend/next.config.mjs` — `headers()` (web build only) and
  `poweredByHeader: false`. Exports a function of `phase` so `next dev` gets
  `'unsafe-eval'`, which React needs in development only.
- `frontend/scripts/inject-csp.mjs` — post-build: writes a hash-based CSP
  `<meta>` into every prerendered document. Wired into `npm run build` and
  `npm run build:mobile`, **before** `build-sw.mjs` (the service worker's cache
  name digests these documents' bytes).
- `frontend/android/app/src/main/res/xml/data_extraction_rules.xml` (API 31+)
  and `backup_rules.xml` (API 30 and lower), referenced from
  `AndroidManifest.xml`.

## The backend origin

`connect-src` is `'self'` plus the origin of `NEXT_PUBLIC_API_BASE_URL`, the
same variable the client bundle inlines (`infrastructure/apiBase.ts`; the
fallback `http://localhost:8000` is duplicated in `csp.mjs` and must stay in
step). `next.config.mjs` reads it from the environment Next has loaded;
`inject-csp.mjs` loads the same `.env*` files through `@next/env`. In Docker it
comes from the `NEXT_PUBLIC_API_BASE_URL` build arg. No hostnames are
hard-coded. **A build pointed at one backend cannot talk to another**: that is
the point, and it is also why a mis-set variable now fails as a CSP violation
in the console rather than a CORS error.

**The identity provider origin (auth phase 2).** When
`NEXT_PUBLIC_SUPABASE_URL` is set, its exact origin (https only, apart from
localhost) is added to `connect-src` by `authOriginFrom` in `csp.mjs`, in the
web header and in the export's meta policy. When it is blank, sign-in is off
and nothing is added. There is deliberately **no `https://*.supabase.co`
fallback**: a wildcard would let a script that read the BYOK key post it to
any Supabase project, including an attacker's. `securityHeaders()` defaults
the origin from the environment, so `next.config.mjs` did not change; a
running `next dev` still serves the policy it computed at start and needs a
restart to pick up a newly set URL.

## The policy

Web header (production, dev origin shown as `<api>`):

```
default-src 'self'; connect-src 'self' <api>; img-src 'self' data: blob:;
media-src 'self' blob:; style-src 'self' 'unsafe-inline'; font-src 'self';
worker-src 'self'; manifest-src 'self'; frame-src 'none'; object-src 'none';
base-uri 'self'; form-action 'self'; script-src 'self' 'unsafe-inline';
frame-ancestors 'none'
```

Plus `Referrer-Policy: same-origin` (stricter than
strict-origin-when-cross-origin; the backend reads `Origin`, never `Referer`),
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Strict-Transport-Security: max-age=31536000` (no `includeSubDomains`, no
`preload`: the production domain's siblings are not this app's to pin), and a
`Permissions-Policy` turning off camera, microphone, geolocation, payment,
usb, serial, hid, midi, display-capture and the motion sensors. `web-share`
(Share notes) and `clipboard-write` (Copy) are deliberately left alone; the
file picker's camera option is the OS chooser, not `getUserMedia`.

Per-document meta, web build: `script-src 'self' 'sha256-…' …` (the hashes of
that file's inline scripts, typically 3 or 4). Capacitor export: the whole
header policy minus `frame-ancestors` (a meta tag cannot set it), with the
hashes in place of `'unsafe-inline'`.

Directive notes:
- `img-src` — thumbnails are `data:` URLs, History posters `blob:`, platform
  icons same-origin files. A remote image in the model's notes markdown is
  now **blocked on purpose** (it would be a beacon); none is expected.
- `media-src blob:` — UploadForm reads a picked file's duration through a
  detached `<video>`/`<audio>` on a `blob:` URL.
- `style-src 'unsafe-inline'` — React server-renders `style=""` attributes
  (GFM table alignment and others); hashes cannot cover attributes without
  `'unsafe-hashes'`. CSS cannot read the key, and with `img-src`/`font-src`
  locked it cannot carry anything out.

## script-src: hashes, not nonces, not plain 'unsafe-inline'

Next's App Router inlines `self.__next_f.push(…)` RSC scripts and the root
layout inlines `PRE_PAINT_SCRIPT`. Nonces need per-request rendering and every
route here is static (`○` in the build table). Next's experimental SRI only
covers external chunks, not inline scripts. But a static document's inline
scripts are fixed at build time, so `inject-csp.mjs` hashes exactly the inline
scripts in each prerendered `.html` (web: `.next/server/app/` **and**
`.next/standalone/.next/server/app/`, the copy the Docker image serves;
export: all of `out/`) and writes a meta policy after `<meta charSet>`, before
every script (the function throws if a script would precede it).

A document obeys every policy it carries, so on the web the effective rule is
the intersection: header `'unsafe-inline'` AND meta hashes = hashes only. The
header keeps `'unsafe-inline'` so that a response Next renders at request time
(none today) degrades to "works, weaker" instead of "blank page". External
chunks are `'self'`. Client navigations fetch RSC data, never new inline
scripts, so the first document's policy stays valid across navigations.

**The build now refuses a dynamic route** (2026-11-07): `inject-csp.mjs` reads `.next/app-path-routes-manifest.json` and `.next/prerender-manifest.json` and exits 1 if any page route is not prerendered, naming it. Before, such a route silently lost the meta and ran under the header's `'unsafe-inline'` with nothing turning red. `@next/env`, which the script imports, is now a declared devDependency (pinned to the same major as `next`) rather than a transitive one.

**If you add an inline script** (another pre-paint snippet, `next/script`
inline content), nothing to do: the next build hashes it. **If a route becomes
dynamic**, it loses the meta and runs under the header alone
(`'unsafe-inline'`); connect-src/img-src still hold. **Do not add
`'unsafe-eval'` to production.**

What CSP cannot stop: a script that has already run can still navigate the
whole page to another host with the key in the URL (`navigate-to` never
shipped). The hashes are what make that script unable to run.

## Capacitor / Android

The WebView origin is `https://localhost`; the backend is cross-origin. The
Capacitor bridge is injected by the native side, either through a
document-start script or by `JSInjector` right after `<head>`, in both cases
before the meta policy exists, so it is not subject to it; native→JS calls go
through `evaluateJavascript`, which page CSP does not govern. Verified on the
API 36 emulator with the bundled APK (2026-11-07): App.getInfo, the update
check (`/api/releases`), free-runs and capabilities calls, SystemBars night
sync, the share intent filling the link field, the file picker opening
DocumentsUI, and the AI Studio link opening Chrome. Zero CSP messages other
than deliberate probes.

## Android backups

`allowBackup` stays `true`. Both rule files exclude
`root:app_webview/Default/Local Storage/`, the Chromium WebView's
localStorage directory (verified on the emulator: the key is in
`Local Storage/leveldb/000003.log`); `data_extraction_rules.xml` excludes it
from both `cloud-backup` and `device-transfer`. Everything else, including
IndexedDB History (`app_webview/Default/IndexedDB/`), is backed up as before.

Verified end to end with the local transport: seeded a fake key and an
IndexedDB record, `bmgr backupnow`, `pm clear`, `bmgr restore`, relaunched:
the IndexedDB record came back, the key read `null`. (A force-stopped app is
not eligible for backup; `bmgr` then says "Backup is not allowed".)

Side effect: the rest of localStorage — theme choice, the Welcome flag, the
free-run device token, the client id — is not restored on a new phone either;
those start fresh.

## Known issues

- `Error injecting safe area CSS` in logcat at launch is pre-existing (see
  `app-shell-layout.md`), not CSP.
- `next start` warns that it does not support `output: standalone`; it still
  serves the hashed pages. Production runs `node server.js` from the
  standalone output, also verified.

## Changelog

- 2026-11-07 · frontend agent · created: security headers + CSP for the web build, hash-based meta CSP for both builds, Android backup rules excluding WebView Local Storage
- 2026-11-07 · security-check · `inject-csp.mjs` fails the web build on any non-prerendered page route; `@next/env` declared in package.json
- 2026-11-08 · frontend subagent (auth phase 2) · `connect-src` gains the exact origin of `NEXT_PUBLIC_SUPABASE_URL` (`authOriginFrom`), nothing when blank; no `*.supabase.co` wildcard, on purpose
- 2026-11-13 · frontend agent · reviewed for billing (Stripe Checkout/Portal by top-level redirect): no change. `connect-src` only governs fetch (billing fetches go to the API origin), navigation is not governed, no form posts to Stripe, `payment=()` does not reach Stripe's page. See `billing.md`
- 2026-11-14 · frontend agent · one more pre-paint snippet, `SESSION_INIT_SCRIPT` (stamps `data-session` from the stored-session key's presence); hashed by the build, no CSP change
