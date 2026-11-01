import { WifiOff } from "lucide-react";
import AppNav from "@/components/AppNav";
import BottomTabBar from "@/components/BottomTabBar";
import SiteFooter from "@/components/SiteFooter";

/* Hallmark · theme: editorial (carried from tokens.css)
 *
 * Chrome is the app's chrome, not an offline-page variant: the same `.shell`
 * frame, the same `<AppNav />`, `<SiteFooter />` and `<BottomTabBar />` that
 * HomeScreen and LegalShell render (the display mode picks which of the last
 * two shows). A standalone route is still the same
 * application, so it does not get its own furniture.
 *
 * `activeTab={null}`: none of the four is where you are.
 *
 * The tabs point at `/?view=…`, which the service worker deliberately answers
 * with this page while the network is down (`/` needs the API; serving the
 * cached shell would give an upload form that cannot upload). So tapping
 * History offline lands back here. That is the honest answer to "show me my
 * history with no network", not a dead end — and it is a far smaller problem
 * than the alternative, a route whose chrome visibly differs from every other
 * route. The links are not decorative either: they are real navigations that
 * start working the instant the network does, which is exactly why they must
 * not be rendered as disabled — the page cannot know when connectivity
 * returns, and the first thing a user does on this screen is retry.
 *
 * Phase 4 (design/phase4-boards/Offline*.png): a tint disc with the
 * wifi-off glyph, a serif title, two short lines, actions — centred in a
 * `.view-scroll` section (HomeScreen's scrolling model, no `data-frame`).
 * The boards also say "Your History is still here." and offer Open History;
 * both are left out because they are not true yet — History is fetched from
 * the server, and the worker answers `/?view=history` with this very page
 * while offline. They come back when history moves client-side.
 *
 * No wordmark in the body. The nav directly above already is one, and two
 * stacked wordmarks read as repetition — the same call the legal footer makes.
 *
 * Plain <a>, not next/link, in the body and footer: this page is served from
 * the service worker cache with the network down, where the RSC payload a
 * client-side navigation wants cannot resolve. HomeScreen's footer uses plain
 * anchors too. AppNav's tabs *are* next/link and that is fine — measured
 * offline, the prefetch fails, Next falls back to a document navigation, and
 * the worker answers it.
 * pre-emit critique: P5 H5 E5 S5 R5 V4
 */
export default function OfflinePage() {
  return (
    <div className="shell" data-view="offline">
      <AppNav activeTab={null} />

      <section className="view-scroll" data-view="offline" aria-label="Offline">
        {/* Neutral, not red: nothing failed, the network is just absent. */}
        <div className="offline">
          <span className="offline-frame" aria-hidden="true">
            <WifiOff />
          </span>
          <h1 className="offline-title">You&apos;re offline</h1>
          <p className="offline-lede">
            VideoLens needs a connection to analyze new videos. A run you already started keeps
            going on the server.
          </p>
          <a href="/" className="btn btn-ink btn-pill offline-action">
            Try again
          </a>
        </div>
      </section>

      <SiteFooter />
      <BottomTabBar activeTab={null} />
    </div>
  );
}
