import Link from "next/link";
import RouteNav from "@/components/RouteNav";
import RouteTabBar from "@/components/RouteTabBar";
import SiteFooter from "@/components/SiteFooter";
import SampleResult from "@/components/SampleResult";
import LandingAllowance from "@/components/LandingAllowance";
import { ACCOUNT_FREE_RUNS_PER_DAY } from "@/application/accountAllowance";

/* Hallmark · macrostructure: owner board (design/shots/Landing.png, LandingWeb.png)
 * genre: editorial · theme: custom (app/tokens.css — the owner's handoff)
 * sections: hero + sample card · how it works · what you get · closing band
 * pre-emit critique: P5 H5 E4 S5 R5 V4
 *
 * The landing page at `/` (Phase 5c). The tool moved to `/app`; every call to
 * action goes there.
 *
 * Chrome is the app's chrome, not a marketing variant: the same `.shell`,
 * `<AppNav />`, `<SiteFooter />` and `<BottomTabBar />` every route renders
 * (through `RouteNav` / `RouteTabBar`, which add the Account entry where
 * sign-in is available, 2026-11-14),
 * and the same `.view-scroll` band, so the nav and footer stay put and only
 * the content scrolls. None of the four tabs is current here (none of them is
 * where you are); the brand link is. The installed app never shows this page
 * — `/` sends it straight to `/app` (application/landingRedirect.ts) — but the
 * dock is rendered anyway so the page is correct if that redirect is ever
 * skipped.
 *
 * Copy is held to what the product does today: free runs with no account,
 * your own Gemini key for more, History kept in this browser, files deleted
 * from the server once a run finishes. The only numbers are the server's own
 * (free runs, video length; LandingAllowance, client-side after the reads
 * land) and the account allowance constant. No testimonials. */
export default function LandingScreen() {
  return (
    <div className="shell" data-view="landing">
      {/* Signed out, the account entry says what it gets you ("Get 10 free
          runs"), so it invites new visitors without reading like a second
          "Start analyzing". Outlined: the hero's green CTA is the view's one
          green fill. Other routes keep "Sign in". Between 48rem and 50rem
          the inline bar is 13px too narrow for it, so the pill says "Sign up
          free" there (measured; app/globals.css). */}
      <RouteNav
        activeTab={null}
        landing
        signedOutLabel={`Get ${ACCOUNT_FREE_RUNS_PER_DAY} free runs`}
        signedOutShortLabel="Sign up free"
      />

      <main className="view-scroll" data-view="landing" aria-label="VideoLens AI">
        <div className="landing">
          <div className="landing-hero">
            <div className="landing-intro">
              <p className="eyebrow">Notes from short video</p>
              <h1 className="landing-title">Turn any short video into clean notes.</h1>
              <p className="landing-lede">
                Paste a link or add a file. You get a transcript, the text on screen, a short summary
                and notes you can keep.
              </p>
              <div className="landing-actions">
                <Link href="/app" className="btn btn-primary btn-pill landing-btn">
                  Start analyzing
                </Link>
                <a href="#how" className="btn btn-secondary btn-pill landing-btn">
                  See how it works
                </a>
              </div>
              <LandingAllowance />
            </div>

            <SampleResult />
          </div>

          <section id="how" className="landing-block" aria-labelledby="how-title">
            <h2 id="how-title" className="landing-h2">
              How it works
            </h2>
            <ol className="landing-steps">
              <li className="landing-step">
                <span className="landing-step-num" aria-hidden="true">
                  01
                </span>
                <h3 className="landing-step-title">Paste or drop</h3>
                <p className="landing-step-text">
                  Paste a YouTube, TikTok or Instagram link, or add an audio or video file.
                </p>
              </li>
              <li className="landing-step">
                <span className="landing-step-num" aria-hidden="true">
                  02
                </span>
                <h3 className="landing-step-title">VideoLens reads it</h3>
                <p className="landing-step-text">
                  It listens to the speech and reads the text on screen.
                </p>
              </li>
              <li className="landing-step">
                <span className="landing-step-num" aria-hidden="true">
                  03
                </span>
                <h3 className="landing-step-title">Read and keep</h3>
                <p className="landing-step-text">
                  Get a summary, notes and a transcript you can copy or download.
                </p>
              </li>
            </ol>
          </section>

          <section className="landing-block landing-wyg" aria-labelledby="landing-wyg-title">
            <h2 id="landing-wyg-title" className="landing-h2">
              What you get
            </h2>
            <dl className="landing-wyg-list">
              <div className="wyg-row">
                <dt className="chip">TL;DR</dt>
                <dd>A short read of what the video says.</dd>
              </div>
              <div className="wyg-row">
                <dt className="chip">Notes</dt>
                <dd>Structured notes to copy or download.</dd>
              </div>
              <div className="wyg-row">
                <dt className="chip">Transcript</dt>
                <dd>Timestamped, with speakers when clear.</dd>
              </div>
              <div className="wyg-row">
                <dt className="chip">On-screen</dt>
                <dd>Text, code and charts from the frames.</dd>
              </div>
            </dl>
            <dl className="landing-wyg-foot landing-details">
              <div>
                <dt>Your files</dt>
                <dd>Your video is deleted when the run finishes. The result is kept for up to an hour, then deleted.</dd>
              </div>
              <div>
                <dt>Your history</dt>
                <dd>Saved in this browser, so you can come back to your notes.</dd>
              </div>
              <div>
                <dt>When today&apos;s runs are used</dt>
                <dd>
                  They come back every day. To keep going sooner, use your own Gemini key.{" "}
                  <Link href="/app?view=api-key" className="text-link">
                    Use your own Gemini key
                  </Link>
                </dd>
              </div>
            </dl>
          </section>

          <section className="landing-band" aria-labelledby="landing-band-title">
            <h2 id="landing-band-title" className="landing-band-title">
              Have a video in mind?
            </h2>
            <Link href="/app" className="btn btn-primary btn-pill landing-btn">
              Start analyzing
            </Link>
          </section>
        </div>
      </main>

      <SiteFooter />
      <RouteTabBar activeTab={null} />
    </div>
  );
}
