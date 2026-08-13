import type { Metadata, Viewport } from "next";
import ServiceWorkerRegistration from "@/components/ServiceWorkerRegistration";
import UpdateBanner from "@/components/UpdateBanner";
import { AppBackground } from "@/components/ui/AppBackground";
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
  themeColor: "#0b0d0c",
  colorScheme: "dark",
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-[100dvh] overflow-hidden">
      <body className="h-[100dvh] overflow-hidden bg-[var(--color-paper)] text-[var(--color-text)] antialiased select-none">
        <AppBackground />
        <div className="safe-area-frame relative h-full w-full overflow-hidden" style={{ zIndex: "var(--z-content)" }}>
          <UpdateBanner />
          {children}
          <ServiceWorkerRegistration />
        </div>
      </body>
    </html>
  );
}
