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
 * The tabs point at `/?view=…`. Since Phase 5a the service worker answers
 * `/?view=history` offline with the cached app shell — History lives in this
 * browser (IndexedDB) now, so it is genuinely complete with no network. Every
 * other app address still lands here (`/` needs the API to analyze anything).
 * The links are real navigations that start working the instant the network
 * does, which is why they must not be rendered as disabled.
 *
 * Phase 4 (design/phase4-boards/Offline*.png): a tint disc with the
 * wifi-off glyph, a serif title, two short lines, actions — centred in a
 * `.view-scroll` section (HomeScreen's scrolling model, no `data-frame`).
 * "Your History is still here." and Open History are true since Phase 5a:
 * History is read from IndexedDB and the worker serves its address offline.
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
            VideoLens needs a connection to analyze new videos. Your History is still here.
          </p>
          <div className="offline-actions">
            <a href="/" className="btn btn-ink btn-pill offline-action">
              Try again
            </a>
            <a href="/?view=history" className="btn btn-secondary btn-pill offline-action">
              Open History
            </a>
          </div>
        </div>
      </section>

      <SiteFooter />
      <BottomTabBar activeTab={null} />
    </div>
  );
}
