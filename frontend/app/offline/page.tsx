import AppNav from "@/components/AppNav";

/* Hallmark · theme: Terminal (locked, carried from tokens.css)
 *
 * Chrome is the app's chrome, not an offline-page variant: the same `.shell`
 * frame, the same `<AppNav />` — brand, all four tabs, drawer and theme toggle,
 * literally the component HomeScreen and LegalShell render — and the same
 * `.page-end > .foot` footer. A standalone route is still the same
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
 * `data-frame="fixed"` locks nav and footer to the viewport. Nothing here
 * scrolls: this is a blocking state, not a document, so it keeps the app's
 * centred `.home-center` + `.run-state` idiom and gets neither the crumb bar
 * nor `.legal-doc`.
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
    <div className="shell" data-view="offline" data-frame="fixed">
      <AppNav activeTab={null} />

      <section data-view="offline" aria-label="Offline">
        <div className="home-center">
          {/* Bare `.run-state` — the app's own centred-state container, at the
              app's own width. The page previously overrode it to 32rem, which
              only re-derived a measure the shell already owns. */}
          <div className="run-state">
            <div className="flex flex-col items-center gap-[var(--space-xs)] text-center">
              <h1 className="page-title">You are offline</h1>
              {/* `.prose` caps at --measure, which is a reading width for
                  left-aligned columns; centred, this sentence spilled one word
                  onto a second line. `balance` splits it into two even lines
                  instead, and degrades to the normal wrap where unsupported. */}
              <p className="prose [text-wrap:balance]">
                Video analysis requires a network connection. Reconnect, then return to your run.
              </p>
            </div>

            <a href="/" className="btn btn-primary">
              Try again
            </a>
          </div>
        </div>
      </section>

      <div className="page-end">
        <footer className="foot">
          <span>VideoLens AI</span>
          <nav className="foot-legal" aria-label="Legal">
            <a href="/privacy">Privacy</a>
            <a href="/terms">Terms</a>
          </nav>
        </footer>
      </div>
    </div>
  );
}
