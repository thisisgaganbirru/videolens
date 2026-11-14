import Link from "next/link";
import RouteNav from "@/components/RouteNav";
import RouteTabBar from "@/components/RouteTabBar";
import SiteFooter from "@/components/SiteFooter";
import SampleResult from "@/components/SampleResult";
import { APP_PATH } from "@/application/useMainTab";

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
 * Copy is held to what the product does today: a few free runs with no
 * account, your own Gemini key for more, History kept in this browser, files
 * deleted from the server once a run finishes. No numbers, no testimonials. */
export default function LandingScreen() {
  return (
    <div className="shell" data-view="landing">
      <RouteNav activeTab={null} landing />

      <main className="view-scroll" data-view="landing" aria-label="VideoLens AI">
        <div className="landing">
          <div className="landing-hero">
            <div className="landing-intro">
              <p className="eyebrow">Notes from short video</p>
              <h1 className="landing-title">Turn any short video into clean notes.</h1>
              <p className="landing-lede">
                Paste a link or add a file. You get a transcript, the text on screen, a short summary
                and notes you can keep. A few free runs to start, no account needed.
              </p>
              <div className="landing-actions">
                <Link href={APP_PATH} className="btn btn-primary btn-pill landing-btn">
                  Start analyzing
                </Link>
                <a href="#how" className="btn btn-secondary btn-pill landing-btn">
                  See how it works
                </a>
              </div>
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
            <p className="landing-wyg-foot">
              Files are deleted from our servers as soon as a run finishes. Your History stays in this
              browser. When the free runs are used up, add your own Gemini key and keep going.
            </p>
          </section>

          <section className="landing-band" aria-labelledby="landing-band-title">
            <h2 id="landing-band-title" className="landing-band-title">
              Have a video in mind?
            </h2>
            <Link href={APP_PATH} className="btn btn-primary btn-pill landing-btn">
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
