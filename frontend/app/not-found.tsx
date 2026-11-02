import type { Metadata } from "next";
import Link from "next/link";
import { Compass } from "lucide-react";
import AppNav from "@/components/AppNav";
import BottomTabBar from "@/components/BottomTabBar";
import SiteFooter from "@/components/SiteFooter";

/* Hallmark · theme: editorial (carried from tokens.css) · sibling of /offline
 *
 * Refinement 6 (OFF-03): an unknown address used to get Next's bare 404 —
 * no nav, no footer, no way back but the browser's own. It is the app's
 * chrome here, as on every route: the same `.shell` frame, `<AppNav />`,
 * `<SiteFooter />` and `<BottomTabBar />` (the display mode picks which of
 * the last two shows), and the content band is the page's one `<main>`.
 *
 * `activeTab={null}`: none of the four is where you are.
 *
 * Same shape as /offline (a tint disc, a serif title, one line, the ways
 * out) because it is the same kind of page, and it shares those rules in
 * globals.css. Neutral, never red: nothing failed, the address is wrong.
 *
 * Static export: Next writes this page as `out/404.html`, which is what the
 * Capacitor build and any static host serve for an unknown path. Offline, the
 * service worker still answers an unknown address with /offline (it cannot
 * tell "no such page" from "needs the network"), which carries the same
 * chrome — see sw/sw.template.js.
 * pre-emit critique: P5 H5 E5 S4 R5 V4
 */

export const metadata: Metadata = {
  title: "Page not found · VideoLens AI",
};

export default function NotFound() {
  return (
    <div className="shell" data-view="not-found">
      <AppNav activeTab={null} />

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
              Open VideoLens
            </Link>
            <Link href="/" className="btn btn-secondary btn-pill not-found-action">
              Go to the home page
            </Link>
          </div>
        </div>
      </main>

      <SiteFooter />
      <BottomTabBar activeTab={null} />
    </div>
  );
}
