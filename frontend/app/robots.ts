import type { MetadataRoute } from "next";
import { SITE_NOINDEX, SITE_URL } from "@/infrastructure/siteOrigin";

export const dynamic = "force-static";

/* `/robots.txt`. Prerendered like every other route, so the static export
   ships it too (Capacitor's asset server never serves it to a crawler, which
   is harmless).

   `/offline` is the service worker's fallback document, not a page anyone
   should land on from a search result. `/app?view=…` is deliberately not
   disallowed: the views are one document whose canonical is `/app`, and a
   crawler has to be allowed to fetch them to read that. */
export default function robots(): MetadataRoute.Robots {
  if (SITE_NOINDEX) {
    return { rules: { userAgent: "*", disallow: "/" } };
  }
  return {
    rules: { userAgent: "*", allow: "/", disallow: "/offline" },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
