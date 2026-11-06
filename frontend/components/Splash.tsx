"use client";

import { BrandMark } from "@/components/AppNav";
import { useSplashHandOff } from "@/application/useFirstRun";

/* Hallmark · component: splash (installed app, cold start) · genre: editorial
 * board: design/shots/SplashApp.png — the mark, the wordmark, the italic serif
 * line, "VideoLens AI" at the foot. Paper background, nothing else.
 * states: hidden (browser tab, warm start) · showing · leaving (200ms fade; none under reduced motion)
 *
 * Always in the /app HTML, shown only while `<html data-splash>` is set — by a
 * pre-paint script (application/firstRunScripts.ts), so on a cold start it is
 * the first frame, not something that pops in after hydration. It never waits
 * on the network; `useSplashHandOff` takes it down ~650ms after navigation
 * start and a CSS timeout takes it down regardless at 2s.
 *
 * On Android it follows the system splash (the launcher icon on paper, from
 * the native `Theme.SplashScreen`), which ends at the WebView's first frame —
 * this frame. So the native splash hands off to this one rather than the two
 * competing; there is no @capacitor/splash-screen plugin to hold it longer.
 *
 * aria-hidden: it says nothing the page does not, and it is gone in under a
 * second. Screen readers go straight to the page underneath. */
export default function Splash() {
  useSplashHandOff();
  return (
    <div className="splash" aria-hidden="true">
      <div className="splash-centre">
        <BrandMark className="splash-mark" />
        <p className="splash-word">videolens</p>
        <p className="splash-line">Notes from short video</p>
      </div>
      <p className="splash-foot">VideoLens AI</p>
    </div>
  );
}
