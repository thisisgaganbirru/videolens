import type { MetadataRoute } from "next";
import { SITE_URL } from "@/infrastructure/siteOrigin";

export const dynamic = "force-static";

/* `/sitemap.xml`: the four public documents. `/offline` and `/404.html` are
   not pages to find, and `/app?view=…` are views of `/app`, whose canonical
   link already says so.

   No `lastModified`: it would have to be either a hand-maintained date that
   rots or the build time, and a date that moves on every deploy tells a
   crawler nothing true about the content. */
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${SITE_URL}/`, changeFrequency: "monthly", priority: 1 },
    { url: `${SITE_URL}/app`, changeFrequency: "monthly", priority: 0.9 },
    { url: `${SITE_URL}/privacy`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${SITE_URL}/terms`, changeFrequency: "yearly", priority: 0.3 },
  ];
}
