import type { Metadata, Viewport } from "next";
import { Hanken_Grotesk, Newsreader } from "next/font/google";
import ServiceWorkerRegistration from "@/components/ServiceWorkerRegistration";
import UpdatePrompt from "@/components/UpdatePrompt";
import { NATIVE_SCHEME_FLAG, SYSTEM_DARK_QUERY, THEME_COLOR, THEME_STORAGE_KEY } from "@/components/theme";
import { SHELL_STORAGE_KEY } from "@/components/shell";
import { LANDING_REDIRECT_SCRIPT } from "@/application/landingRedirect";
import { SPLASH_INIT_SCRIPT } from "@/application/firstRunScripts";
import { FONT_SCALE_INIT_SCRIPT } from "@/application/nativeFontScale";
import { SITE_DESCRIPTION, SITE_NAME, SITE_NOINDEX, SITE_URL } from "@/infrastructure/siteOrigin";
import { BYOK_INIT_SCRIPT } from "@/infrastructure/apiKeyStore";
import { SESSION_INIT_SCRIPT } from "@/infrastructure/authSessionStamp";
import { LAYOUT_HINTS_INIT_SCRIPT } from "@/infrastructure/layoutHints";
import "./globals.css";

/* Self-hosted at build time by next/font — no request to Google at runtime,
   which is what lets the static export (Capacitor) and the offline page keep
   their type. The files land in /_next/static/media and the service worker
   precaches them (scripts/build-sw.mjs).

   Hanken Grotesk is the variable font: the UI uses 400/500/600/700, and one
   variable file is smaller than four static ones. Newsreader is variable too
   since Phase 2: it now sets the Notes and TL;DR reading text, whose markdown
   carries bold headings, **strong** and *emphasis* — a static 400 would have
   the browser synthesise all three. Italic, and the optical-size axis below,
   are the extra bytes that buys.
   The two `variable`s are what `--font-ui` / `--font-serif` in tokens.css
   read. */
const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-hanken",
  display: "swap",
});
const newsreader = Newsreader({
  subsets: ["latin"],
  style: ["normal", "italic"],
  /* The optical-size axis: Newsreader's display cut is what the boards'
     56px headline is set in (narrower and finer than the text cut at the
     same size). Browsers pick the cut from the font size by themselves
     (font-optical-sizing: auto), so nothing in CSS has to ask for it. */
  axes: ["opsz"],
  variable: "--font-newsreader",
  display: "swap",
});

/* Site-wide metadata. Each page sets its own `title` (the template appends
   the site name), `description` and canonical URL; everything else is
   inherited from here. `metadataBase` is what turns the relative icon, image
   and canonical paths into absolute URLs (infrastructure/siteOrigin.ts).

   The Open Graph / Twitter card is one site-level image (`public/og.png`,
   1200×630, rendered from the landing hero) rather than a per-page one: the
   four public pages are one product, and a legal page's link preview should
   still show the product. `alt` is the hero's own line. See
   docs/frontend/seo-and-discovery.md. */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  applicationName: SITE_NAME,
  title: { default: SITE_NAME, template: `%s · ${SITE_NAME}` },
  description: SITE_DESCRIPTION,
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      /* The classic path first: crawlers, link unfurlers and old browsers ask
         for /favicon.ico without reading <link> tags. 48/32/16 in one file. */
      { url: "/favicon.ico", sizes: "48x48 32x32 16x16" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
  },
  openGraph: {
    type: "website",
    siteName: SITE_NAME,
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
    url: "/",
    images: [
      {
        url: "/og.png",
        width: 1200,
        height: 630,
        alt: "VideoLens AI. Turn any short video into clean notes.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
    images: ["/og.png"],
  },
  /* Only the dev deployment sets NEXT_PUBLIC_NOINDEX; production inherits the
     browser default (index, follow), so nothing is written there. */
  ...(SITE_NOINDEX ? { robots: { index: false, follow: false } } : {}),
};

export const viewport: Viewport = {
  // One value, not a prefers-color-scheme pair: a stored choice can disagree
  // with the OS, and a media-switched chrome colour would then paint a dark
  // strip above a light page. The pre-paint script below re-points this tag at
  // the theme actually in use (device-resolved when nothing is stored).
  themeColor: THEME_COLOR.light,
  colorScheme: "light dark",
  // env(safe-area-inset-*) is inert without this — the shell's safe-area
  // padding depends on it.
  viewportFit: "cover",
};

/* Blocking, pre-paint: stamps data-theme on <html> before the first frame so
   the theme doesn't flash. Kept deliberately tiny and inline — a deferred
   script or a React effect both paint the wrong theme first. The same key is
   written by setThemePreference in components/theme.ts (the header toggle,
   and the More sheet's System / Light / Dark choice — System removes it,
   which is what hands the theme back to the listener below; refinement 4).

   A stored "light"/"dark" wins. Nothing stored follows the device
   (prefers-color-scheme), and keeps following it: the listener lives as long
   as the document (client navigations never replace it) and re-reads storage
   on every change, so the moment the user picks a theme it stops acting.
   Refinement 2, #3; it used to be light regardless of the OS.

   In the installed Android app the listener stands down once the native shell
   has reported the OS night state (window[NATIVE_SCHEME_FLAG], set by
   components/theme.ts): the WebView's media query can go stale after a forced
   night mode is lifted, and the native value is then what is painted
   (refinement 7, THM-01b-6). The first paint still uses the media query: on a
   cold launch it is correct, and the native value lands a moment later.

   The meta tag is looked up defensively rather than assumed present: this script
   runs while <head> is still parsing, so Next's own tag may or may not exist
   yet. Appending ours first is harmless — the browser honours the first
   theme-color in document order, which is then always the one we just set. */
const THEME_INIT_SCRIPT = `(function(){var r=document.documentElement,q=null;try{q=window.matchMedia(${JSON.stringify(
  SYSTEM_DARK_QUERY
)});}catch(e){}function s(){var t;try{t=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY
)});}catch(e){}return t==="dark"||t==="light"?t:null;}function a(t){r.setAttribute("data-theme",t);try{var m=document.querySelector('meta[name="theme-color"]');if(!m){m=document.createElement("meta");m.setAttribute("name","theme-color");document.head.appendChild(m);}m.setAttribute("content",t==="dark"?${JSON.stringify(
  THEME_COLOR.dark
)}:${JSON.stringify(THEME_COLOR.light)});}catch(e){}}
a(s()||(q&&q.matches?"dark":"light"));try{q&&q.addEventListener("change",function(e){if(!s()&&!window[${JSON.stringify(
  NATIVE_SCHEME_FLAG
)}])a(e.matches?"dark":"light");});}catch(e){}})();`;

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

/* All four pre-paint scripts, in the order they depend on each other: theme,
   shell (stamps data-shell), then the two route-specific ones that read it —
   the landing redirect (acts only on `/`, and on the Capacitor export's
   extensionless routes) and the splash flag (acts only on the tool's own
   document). The route-specific two used to be rendered by their pages; they
   moved here in refinement 1 because a page's <script> is re-created by React
   on client navigation, which never runs it and logs an error. The root
   layout's head is hydrated, never re-created. See their own files.

   The Android font-scale script (refinement 14) goes first; it depends on
   nothing and only acts in the native app. See application/nativeFontScale.ts.

   The key-presence stamp (2026-11-14, Android QA run 22) goes last and
   depends on nothing: `data-byok` lets CSS drop the free-runs strip's
   reserved height before hydration. See infrastructure/apiKeyStore.ts.
   The session stamp (2026-11-14) follows it the same way: `data-session`
   lets CSS drop the Gemini key page's held sign-in line for a signed-in
   visit. See infrastructure/authSessionStamp.ts. The layout hints
   (2026-11-14) go last: `data-runs-spent` (the out-of-runs block's space on
   Analyze, until the stored reset time) and `data-plan-paid` (the Billing
   card's stand-in on Account). See infrastructure/layoutHints.ts. */
const PRE_PAINT_SCRIPT =
  FONT_SCALE_INIT_SCRIPT +
  THEME_INIT_SCRIPT +
  SHELL_INIT_SCRIPT +
  LANDING_REDIRECT_SCRIPT +
  SPLASH_INIT_SCRIPT +
  BYOK_INIT_SCRIPT +
  SESSION_INIT_SCRIPT +
  LAYOUT_HINTS_INIT_SCRIPT;

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
        <script dangerouslySetInnerHTML={{ __html: PRE_PAINT_SCRIPT }} />
      </head>
      <body className="h-[100dvh] overflow-clip bg-[var(--color-paper)] text-[var(--color-ink)] antialiased select-none">
        <div className="viewport">
          <UpdatePrompt />
          {children}
          <ServiceWorkerRegistration />
        </div>
      </body>
    </html>
  );
}
