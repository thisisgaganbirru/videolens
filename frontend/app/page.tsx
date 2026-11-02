import LandingScreen from "@/components/LandingScreen";
import { LANDING_REDIRECT_SCRIPT } from "@/application/landingRedirect";
import "./landing.css";

/* `/` — the landing page (Phase 5c). The tool is at `/app` (app/app/page.tsx).

   The inline script comes first in the page's markup and runs while the HTML
   is still parsing, before anything of the landing page exists to paint. It
   sends the installed app, old `/?view=…` links and share-target launches on
   to `/app` (and, in the Capacitor export, `/app` itself on to `/app.html`);
   see application/landingRedirect.ts for the rules. A plain browser visit to
   `/` falls through it and gets the page below. */
export default function Page() {
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: LANDING_REDIRECT_SCRIPT }} />
      <LandingScreen />
    </>
  );
}
