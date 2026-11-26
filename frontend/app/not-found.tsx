import type { Metadata } from "next";
import Link from "next/link";
import { Compass } from "lucide-react";
import RouteNav from "@/components/RouteNav";
import RouteTabBar from "@/components/RouteTabBar";
import SiteFooter from "@/components/SiteFooter";

/* Hallmark · theme: editorial (carried from tokens.css) · sibling of /offline
 *
 * Refinement 6 (OFF-03): an unknown address used to get Next's bare 404 —
 * no nav, no footer, no way back but the browser's own. It is the app's
 * chrome here, as on every route (nav and dock through `RouteNav` /
 * `RouteTabBar`, which add the Account entry): the same `.shell` frame, `<AppNav />`,
 * `<SiteFooter />` and `<BottomTabBar />` (the display mode picks which of
 * the last two shows), and the content band is the page's one `<main>`.
 *
 * `activeTab={null}`: none of the four is where you are.
 *
 * Same shape as /offline (a tint disc, a serif title, one line, the ways
 * out) because it is the same kind of page, and it shares those rules in
 * globals.css. Neutral, never red: nothing failed, the address is wrong.
 *
 * Static export: Next writes this page as `out/404.html`, which is what a
 * static host serves for an unknown path. Capacitor's asset server does not:
 * it answers an unknown extensionless path with index.html, so the head
 * script (application/landingRedirect.ts) sends the installed app here at
 * `/404.html` (refinement 8, NF-01). In the installed shell "Go to the home
 * page" is hidden: the home page is the landing, which the installed app
 * never shows, and a client-side navigation to `/` would render it without
 * the head script's redirect. Offline, the
 * service worker still answers an unknown address with /offline (it cannot
 * tell "no such page" from "needs the network"), which carries the same
 * chrome — see sw/sw.template.js.
 * pre-emit critique: P5 H5 E5 S4 R5 V4
 */

/* No `robots` here: Next already writes `noindex` on every not-found
   document, and a second meta would only repeat it. */
export const metadata: Metadata = {
  title: "Page not found",
};

export default function NotFound() {
  return (
    <div className="shell" data-view="not-found">
      <RouteNav activeTab={null} />

      <main className="view-scroll" data-view="not-found" aria-labelledby="not-found-title">
        <div className="not-found">
          <span className="not-found-frame" aria-hidden="true">
            <Compass />
          </span>
          <h1 id="not-found-title" className="not-found-title">
            This page doesn&apos;t exist.
          </h1>
          <p className="not-found-lede">The address may be mistyped, or the page has moved.</p>
          <div className="not-found-actions">
            <Link href="/app" className="btn btn-ink btn-pill not-found-action">
              Open the app
            </Link>
            <Link href="/" className="btn btn-secondary btn-pill not-found-action not-found-action--web">
              Home page
            </Link>
          </div>
        </div>
      </main>

      <SiteFooter />
      <RouteTabBar activeTab={null} />
    </div>
  );
}
