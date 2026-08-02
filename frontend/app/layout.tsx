import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VideoLens AI",
  description: "Upload a short video and get a transcript, on-screen text, summary, and notes.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#0b0d0c] text-slate-100 antialiased">{children}</body>
    </html>
  );
}
