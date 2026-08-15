import type { Metadata, Viewport } from "next";
import ServiceWorkerRegistration from "@/components/ServiceWorkerRegistration";
import UpdateBanner from "@/components/UpdateBanner";
import { DEFAULT_THEME, THEME_COLOR, THEME_STORAGE_KEY } from "@/components/theme";
import "./globals.css";

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

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
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
