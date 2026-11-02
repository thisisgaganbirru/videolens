import type { MetadataRoute } from "next";

export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "VideoLens AI",
    short_name: "VideoLens",
    description: "Turn short media into transcripts, timelines, summaries, and notes.",
    /* Phase 5c. `id` is pinned to "/" because that is the id every existing
       install already has: the old manifest had no `id`, and a browser then
       uses `start_url` ("/") as the app's identity. Keeping it means a
       changed `start_url` updates those installs in place instead of turning
       them into a second, different app. `start_url` now opens the tool
       directly; `scope` stays the whole origin so the landing page, the legal
       pages and /offline are all inside the installed app. */
    id: "/",
    start_url: "/app",
    scope: "/",
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
    shortcuts: [
      { name: "Analyze", short_name: "Analyze", url: "/app" },
      { name: "History", short_name: "History", url: "/app?view=history" },
    ],
    share_target: {
      action: "/app?share-target=1",
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
