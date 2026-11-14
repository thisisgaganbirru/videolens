# SEO and discovery: metadata, sitemap, robots, social preview, favicon

How the web app describes itself to search engines, link unfurlers and
browser chrome. Added 2026-11-12 from a pre-launch audit against a
19-item checklist (the full audit table is at the end, so the next person
does not re-derive what was already there).

## Files

| File | What it does |
|---|---|
| `infrastructure/siteOrigin.ts` | `SITE_URL` (from `NEXT_PUBLIC_SITE_URL`, falling back to the production Railway domain), `SITE_NOINDEX` (`NEXT_PUBLIC_NOINDEX=1`), `SITE_NAME`, `SITE_DESCRIPTION`. The one place every absolute self-URL comes from. |
| `app/layout.tsx` `metadata` | `metadataBase`, the title template (`%s · VideoLens AI`), site description, `application-name`, icons (favicon.ico first, then the PNGs, apple-touch-icon), Open Graph and Twitter card pointing at `/og.png`, and a `noindex` robots meta when `SITE_NOINDEX`. |
| `app/page.tsx`, `app/app/page.tsx`, `app/privacy/page.tsx`, `app/terms/page.tsx` | Per-page `title`, `description` and `alternates.canonical`. The landing uses `title.absolute` so the home tab reads "VideoLens AI · Turn any short video into clean notes" instead of a templated string. `/app` is the canonical for every `?view=`. |
| `app/offline/page.tsx` | `noindex, nofollow`: the service worker's fallback document is not a search result. `not-found.tsx` relies on the `noindex` Next writes on its own. |
| `app/sitemap.ts` | `/sitemap.xml` with `/`, `/app`, `/privacy`, `/terms`. No `lastModified` (a build-time date would move on every deploy and say nothing true). |
| `app/robots.ts` | `/robots.txt`: allow all, `Disallow: /offline`, `Sitemap:` line. With `SITE_NOINDEX`, `Disallow: /` instead. |
| `next.config.mjs` | Adds `X-Robots-Tag: noindex, nofollow` to every response when `NEXT_PUBLIC_NOINDEX=1` (covers images, the manifest and sitemap.xml itself, which a meta tag cannot). |
| `public/og.png` | The social preview, 1200×630, 29 KB. Rendered from an HTML board using the site's own self-hosted Hanken Grotesk and Newsreader files, then quantised to 255 colours. One site-level image on purpose: the four public pages are one product. |
| `public/favicon.ico` | 48/32/16 from `icon-512.png`. Crawlers, unfurlers and old browsers ask for `/favicon.ico` without reading `<link>` tags. |
| `frontend/Dockerfile` | Declares `NEXT_PUBLIC_SITE_URL` and `NEXT_PUBLIC_NOINDEX` as build `ARG`s so Railway's service variables reach the build stage. Both optional. |

Both routes are `force-static`, so the Capacitor export (`npm run
build:mobile`) writes `out/robots.txt` and `out/sitemap.xml` too. Harmless:
the asset server never serves them to a crawler. `scripts/inject-csp.mjs`
only asserts page routes are prerendered, so the two metadata routes do not
trip it, and the CSP is unchanged (everything new is same-origin).

## Environment variables

Neither is set anywhere yet. Production works without them because the
fallback is the production domain.

- `NEXT_PUBLIC_SITE_URL`: set when the site moves to a custom domain, or the
  canonical links and sitemap will keep naming the Railway domain.
- `NEXT_PUBLIC_NOINDEX=1`: should be set on the **dev** frontend service in
  Railway so the dev site is not indexed as a duplicate. Until it is, the dev
  pages at least declare production as their canonical copy. Setting a
  Railway variable is the owner's call (`CLAUDE.md`, Railway rules), so it was
  left for them.

## Regenerating the preview image

There is no script checked in; the render was a one-off with Playwright over
an HTML board (fonts from `.next/static/media` after a build, viewport
1200×630, `deviceScaleFactor: 1`), followed by
`convert og-raw.png -strip -dither None -colors 255 og.png`. The board's copy
is the landing hero: eyebrow, headline, lede, the four chips. If the hero
copy changes, re-render so the card and the page agree.

## Icon compression (2026-11-12)

The four PNGs under `public/` were re-encoded. `icon-192`, `icon-512` and
`apple-touch-icon` were quantised to 255 colours (PSNR ≈ 50 dB against the
originals, i.e. not visibly different): 31 → 10 KB, 199 → 65 KB, 27 → 9 KB.
`icon-1024.png` (actually 1254×1254, referenced by nothing in the repo;
presumably the store-listing source) was only stripped losslessly, 960 → 858
KB, because a source asset should not be quantised. It still ships in every
build and APK; moving it out of `public/` is an open suggestion.

## Verification (2026-11-12, production build on localhost)

- `npx tsc --noEmit` clean; `npm run lint` at the 4 known errors + 1 warning.
- `npm run build` and `npm run build:mobile` both pass; `out/` carries
  `robots.txt`, `sitemap.xml`, `og.png`, `favicon.ico`, `404.html`.
- Every internal link and asset on `/`, `/app` (all views), `/privacy`,
  `/terms`, `/offline` and a 404 page returns 200; the one in-page anchor
  (`#how`) has its target. The absolute canonical/sitemap URLs could not be
  fetched from the sandbox (no DNS for the Railway domain), so they are
  unverified end to end.
- No horizontal overflow at 390 px or 1280 px on `/`, `/app`, `/privacy`, 404.
- Lighthouse 12, mobile emulation, localhost: `/` performance 87,
  accessibility 100, best practices 100, SEO 100; `/app` 81 / 100 / 96 / 100.
  Performance is held back by LCP under simulated throttling (3.9 s / 4.4 s,
  the serif headline waiting on fonts and render-blocking CSS); the
  best-practices point on `/app` is the console error from the API not
  running in the sandbox. Nothing was tuned for this; the numbers are a
  baseline.

## The 19-item launch audit (2026-11-12)

| # | Item | State before | Action |
|---|---|---|---|
| 1 | sitemap + robots.txt | missing | added (`app/sitemap.ts`, `app/robots.ts`) |
| 2 | privacy policy page | `/privacy` exists | per-page title/description/canonical added. **The "Contact" clause is still a placeholder** ("Before public release, replace this section with the verified operator contact address"); only the owner can fill it |
| 3 | terms page | `/terms` exists | per-page title/description/canonical added |
| 4 | cookie consent banner | none | **deliberately not added.** The site sets no cookies and runs no trackers; storage is localStorage/IndexedDB for the app's own function (theme, shell, BYOK key, History, device token), which needs no consent banner. A banner here would claim a data practice the site does not have. Revisit only if analytics (19) is adopted |
| 5 | secrets off the frontend | already so | verified: the only `NEXT_PUBLIC_*` values are the API origin, the version string and now the site origin/noindex flag. The Gemini BYOK key is the user's own, stored client-side by design, never in the bundle |
| 6 | social preview image | missing | added `public/og.png` + Open Graph/Twitter metadata |
| 7 | force HTTPS | HSTS on both apps | unchanged. Railway terminates TLS and redirects plain HTTP on its domains; not verifiable from the sandbox, so treat as a shallow check |
| 8 | mobile responsiveness | PWA-first layout | verified at 390 px, no overflow |
| 9 | meta titles and descriptions | one site-wide title/description | per-page titles (template), descriptions, canonicals, `application-name` |
| 10 | custom 404 page | `not-found.tsx` with the app chrome | title now uses the template |
| 11 | alt text for images | the two `<img>`s are decorative with empty `alt` and a labelled parent; everything else is SVG with `aria-hidden` | unchanged |
| 12 | image compression | 1.2 MB of PNG icons | icons re-encoded, see above |
| 13 | page load speed | not measured | Lighthouse baseline recorded above |
| 14 | colour contrast | audited in `design-direction-editorial.md` (every text pair ≥ 4.5) | unchanged; Lighthouse accessibility 100 |
| 15 | favicon | PNG `<link rel="icon">`s only, no `/favicon.ico` | added `public/favicon.ico` |
| 16 | broken links | not checked | crawled, none broken |
| 17 | form validation | `UploadForm` validates file type/size/duration, URL shape, the terms checkbox, with `aria-invalid` and focus to the first error | unchanged |
| 18 | spam protection | no contact form; the intake is behind per-IP rate limit, per-device free runs, a daily cap and the SSRF guard (`docs/backend/cost-abuse-protection.md`) | unchanged |
| 19 | analytics | none | **not added.** Picking a vendor changes the CSP (`connect-src`), the privacy policy and whether item 4 is needed; that is a product decision. If wanted, a cookieless, self-hosted option (Plausible or Umami on Railway) fits the current privacy posture best and would need one `connect-src` entry in `security/csp.mjs` plus a privacy-page clause |

## Known issues

- Open Graph `url` and `title` are the site-level ones on every page (a
  page-level `openGraph` replaces the whole object, so per-page values would
  mean repeating the image block four times). Acceptable for one product;
  revisit if a page ever needs its own card.
- The canonical for `/` renders without a trailing slash
  (`https://host`), which is how Next serialises `metadataBase` + `/`.
  Equivalent to the slash form for crawlers.

## Changelog

- 2026-11-12 · launch-checklist session · created: site origin module, sitemap, robots, per-page metadata, Open Graph/Twitter card and `og.png`, `favicon.ico`, icon compression, noindex switch, the 19-item audit table and Lighthouse baseline
