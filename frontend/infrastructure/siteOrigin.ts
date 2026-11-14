/* The web app's own public origin, in one place.
 *
 * It is what every absolute URL the site publishes about itself is built
 * from: `metadataBase` (canonical links, the Open Graph image), the sitemap's
 * entries and the `Sitemap:` line in robots.txt. Inlined at build time like
 * `API_BASE_URL` (apiBase.ts), so a build is bound to one public origin.
 *
 * The fallback is the production Railway domain rather than localhost: a
 * build that forgot the variable then publishes the right canonical URLs
 * instead of `http://localhost:3005/...`, which a crawler would index as the
 * page's address. The dev deployment points at production too, on purpose:
 * its pages then declare production as the canonical copy, which is the
 * outcome wanted even if a crawler finds the dev site.
 *
 * `SITE_NOINDEX` (`NEXT_PUBLIC_NOINDEX=1`) is for the deployments that must
 * not be indexed at all (dev): it turns robots.txt into `Disallow: /`, adds a
 * `noindex` robots meta to every page and an `X-Robots-Tag` response header
 * (next.config.mjs). Production never sets it. */
export const PRODUCTION_SITE_URL = "https://videolens-frontend-production.up.railway.app";

export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || PRODUCTION_SITE_URL).replace(/\/+$/, "");

export const SITE_NOINDEX = process.env.NEXT_PUBLIC_NOINDEX === "1";

export const SITE_NAME = "VideoLens AI";

/** The one-line description search results and link previews show. */
export const SITE_DESCRIPTION =
  "Turn any short video into clean notes: a transcript, the text on screen, a short summary and notes you can keep. A few free runs, no account needed.";
