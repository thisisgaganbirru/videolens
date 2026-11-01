import type { Metadata, Viewport } from "next";
import { Hanken_Grotesk, Newsreader } from "next/font/google";
import ServiceWorkerRegistration from "@/components/ServiceWorkerRegistration";
import UpdateBanner from "@/components/UpdateBanner";
import { DEFAULT_THEME, THEME_COLOR, THEME_STORAGE_KEY } from "@/components/theme";
import { SHELL_STORAGE_KEY } from "@/components/shell";
import "./globals.css";

/* Self-hosted at build time by next/font — no request to Google at runtime,
   which is what lets the static export (Capacitor) and the offline page keep
   their type. The files land in /_next/static/media and the service worker
   precaches them (scripts/build-sw.mjs).

   Hanken Grotesk is the variable font: the UI uses 400/500/600/700, and one
   variable file is smaller than four static ones. Newsreader is headlines
   only, at 400, so it loads that one static weight. The two `variable`s are
   what `--font-ui` / `--font-serif` in tokens.css read. */
const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-hanken",
  display: "swap",
});
const newsreader = Newsreader({
  subsets: ["latin"],
  weight: "400",
  style: "normal",
  variable: "--font-newsreader",
  display: "swap",
});

export const metadata: Metadata = {
  title: "VideoLens AI",
  description: "Upload a short video and get a transcript, on-screen text, summary, and notes.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
  },
};

export const viewport: Viewport = {
  // One value, not a prefers-color-scheme pair: the app's theme no longer
  // tracks the OS (first visit is light either way), so a media-switched chrome
  // colour would paint a dark strip above a light page for any dark-OS visitor.
  // The pre-paint script below re-points this tag at the theme actually in use.
  themeColor: THEME_COLOR[DEFAULT_THEME],
  colorScheme: "light dark",
  // env(safe-area-inset-*) is inert without this — the shell's safe-area
  // padding depends on it.
  viewportFit: "cover",
};

/* Blocking, pre-paint: stamps data-theme on <html> before the first frame so
   the stored light/dark choice doesn't flash. Kept deliberately tiny and
   inline — a deferred script or a React effect both paint the wrong theme
   first. The same key is written by ThemeToggle, which every route renders.

   Nothing stored resolves to light, NOT to prefers-color-scheme: the first-visit
   default is a product decision and it is light. A stored choice still wins.
   `tokens.css` carries no @media (prefers-color-scheme: dark) block, so there is
   no stylesheet rule left to fight this.

   The meta tag is looked up defensively rather than assumed present: this script
   runs while <head> is still parsing, so Next's own tag may or may not exist
   yet. Appending ours first is harmless — the browser honours the first
   theme-color in document order, which is then always the one we just set. */
const THEME_INIT_SCRIPT = `(function(){var t;try{t=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY
)});}catch(e){}if(t!=="dark"&&t!=="light"){t=${JSON.stringify(DEFAULT_THEME)};}
document.documentElement.setAttribute("data-theme",t);try{var m=document.querySelector('meta[name="theme-color"]');if(!m){m=document.createElement("meta");m.setAttribute("name","theme-color");document.head.appendChild(m);}m.setAttribute("content",t==="dark"?${JSON.stringify(
  THEME_COLOR.dark
)}:${JSON.stringify(THEME_COLOR.light)});}catch(e){}})();`;

/* Blocking, pre-paint, same reason as the theme script: stamps
   `<html data-shell="app"|"web">` so the right chrome (bottom tab bar vs top
   menu + footer) is on screen at first paint. Both are rendered; CSS shows
   one. See components/shell.ts.

   Installed = a standalone PWA (`display-mode: standalone`, or iOS's
   `navigator.standalone`) or the Capacitor native shell. Capacitor's bridge
   object is normally injected ahead of this script, but that is the platform's
   ordering, not ours — so if detection says "web" it is re-checked once at
   DOMContentLoaded. A stored `videolens_shell` of "app"/"web" overrides both
   (testing only). Everything is in try/catch: a failure leaves "web", which is
   also what the stylesheet assumes with no attribute at all. */
const SHELL_INIT_SCRIPT = `(function(){var r=document.documentElement,s;try{s=localStorage.getItem(${JSON.stringify(
  SHELL_STORAGE_KEY
)});}catch(e){}function d(){try{var w=window,c=w.Capacitor;return(w.matchMedia&&w.matchMedia("(display-mode: standalone)").matches)||w.navigator.standalone===true||!!(c&&c.isNativePlatform&&c.isNativePlatform());}catch(e){return false;}}
if(s==="app"||s==="web"){r.setAttribute("data-shell",s);return;}r.setAttribute("data-shell",d()?"app":"web");
if(r.getAttribute("data-shell")==="web"){document.addEventListener("DOMContentLoaded",function(){if(d())r.setAttribute("data-shell","app");});}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`h-full ${hanken.variable} ${newsreader.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT + SHELL_INIT_SCRIPT }} />
      </head>
      <body className="h-[100dvh] overflow-clip bg-[var(--color-paper)] text-[var(--color-ink)] antialiased select-none">
        <div className="viewport">
          <UpdateBanner />
          {children}
          <ServiceWorkerRegistration />
        </div>
      </body>
    </html>
  );
}
