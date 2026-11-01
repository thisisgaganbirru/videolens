import type { MetadataRoute } from "next";

export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "VideoLens AI",
    short_name: "VideoLens",
    description: "Turn short media into transcripts, timelines, summaries, and notes.",
    start_url: "/",
    display: "standalone",
    // The light `--color-paper`. Light is the first-run theme, so the splash
    // and the install-time chrome match the page that then paints.
    background_color: "#F6F4EE",
    theme_color: "#F6F4EE",
    orientation: "portrait-primary",
    icons: [
      {
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    share_target: {
      action: "/?share-target=1",
      method: "GET",
      enctype: "application/x-www-form-urlencoded",
      params: {
        title: "title",
        text: "text",
        url: "url",
      },
    },
  };
}
