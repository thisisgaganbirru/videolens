import { Suspense } from "react";
import HomeScreen, { RoutedHomeScreen } from "@/components/HomeScreen";
import Splash from "@/components/Splash";
import Welcome from "@/components/Welcome";
import { SPLASH_INIT_SCRIPT } from "@/application/firstRunScripts";
import "../first-run.css";

/* The tool: Analyze, History, API key and Releases, addressed as
   `/app?view=…`. It lived at `/` until Phase 5c, when `/` became the landing
   page; the landing page sends old `/` links, shares and installed launches on
   to here (application/landingRedirect.ts).

   The Suspense boundary is a Next.js requirement, not a design choice, which is
   why it lives in `app/`: the active tab is a search param, and on a statically
   rendered route (every route here — the Capacitor build is `output: "export"`)
   Next resolves search params on the client and renders the nearest fallback
   into the prerendered HTML. Without a boundary `next build` fails.

   The fallback is a real Analyze shell rather than a spinner or `null`, so the
   prerendered HTML is the finished page for `/app` — the overwhelmingly common
   entry point — instead of a placeholder that swaps in after hydration. The one
   honest cost: a deep link to `/app?view=history` paints Analyze for the frame
   before hydration, because no static file can know the query string. */

/* Phase 5d, installed app only: the splash's pre-paint flag script, then the
   splash itself, ahead of the tool in the markup so a cold start's first frame
   is the splash; Welcome is a modal dialog over the tool, which stays mounted
   underneath it (so a share still lands in the intake). Both are inert in a
   browser tab. See application/useFirstRun.ts. */
export default function AppPage() {
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: SPLASH_INIT_SCRIPT }} />
      <Splash />
      <Suspense fallback={<HomeScreen activeTab="analyze" />}>
        <RoutedHomeScreen />
      </Suspense>
      <Welcome />
    </>
  );
}
