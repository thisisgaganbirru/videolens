import type { Metadata, Viewport } from "next";
import ServiceWorkerRegistration from "@/components/ServiceWorkerRegistration";
import UpdateBanner from "@/components/UpdateBanner";
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
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#0b0d0c] text-slate-100 antialiased">
        <UpdateBanner />
        {children}
        <ServiceWorkerRegistration />
      </body>
    </html>
  );
}
