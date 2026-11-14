import type { Metadata } from "next";
import LandingScreen from "@/components/LandingScreen";
import "./landing.css";

/* `/` — the landing page (Phase 5c). The tool is at `/app` (app/app/page.tsx).

   The redirect that sends the installed app, old `/?view=…` links and
   share-target launches on to `/app` (and, in the Capacitor export, `/app`
   itself on to `/app.html`) runs from the root layout's <head>, before this
   page is parsed; see application/landingRedirect.ts for the rules and for
   why it no longer lives in this file. A plain browser visit to `/` falls
   through it and gets the page below. */

/* `absolute`: the home page is the one place the bare site name is the
   title, not "Something · VideoLens AI". The description is the hero's lede. */
export const metadata: Metadata = {
  title: { absolute: "VideoLens AI · Turn any short video into clean notes" },
  description:
    "Paste a link or add a file. You get a transcript, the text on screen, a short summary and notes you can keep. Free runs every day, no account needed.",
  alternates: { canonical: "/" },
};

export default function Page() {
  return (
    <LandingScreen />
  );
}
