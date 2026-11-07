import type { RunPlatform } from "./entities";

/* One spelling per platform, everywhere it is named (refinement 9). Pure: no
   I/O, no React, so the History mapping (application/) and the screens
   (components/) share it.

   Two different values reach the screen. The run's `platform` is the backend's
   own classification (`youtube`, `instagram`, `tiktok`, `audio_file`,
   `video_file`, `other`), used by the History chip. A link's source card shows
   `source_metadata.platform`, which is yt-dlp's extractor key — `Youtube`,
   `Instagram`, `TikTok`, and for variants things like `YoutubeTab`. The source
   card printed that raw, so the same run read "YouTube" in History and
   "Source: Youtube" on its result. Both now go through this module. */

const PLATFORM_NAMES: Record<string, string> = {
  youtube: "YouTube",
  instagram: "Instagram",
  tiktok: "TikTok",
  audio_file: "Audio file",
  video_file: "Video file",
};

const BRANDS = ["youtube", "instagram", "tiktok"] as const;

/** The lower-case key a value belongs to, folding yt-dlp's variant extractors
 *  (`YoutubeTab`, `InstagramStory`, …) onto their platform. */
export function platformKey(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const key = raw.trim().toLowerCase();
  if (!key) return null;
  if (PLATFORM_NAMES[key]) return key;
  return BRANDS.find((brand) => key.startsWith(brand)) ?? key;
}

/** How a known platform is written on screen, or null. `other` (and anything
 *  unrecognised) has no name here: callers choose the fallback, because the
 *  History chip says "Link" where the source card shows the server's value. */
export function knownPlatformName(raw: string | null | undefined): string | null {
  const key = platformKey(raw);
  return key ? (PLATFORM_NAMES[key] ?? null) : null;
}

/** The display name, falling back to the value as the server sent it. */
export function platformName(raw: string): string {
  return knownPlatformName(raw) ?? raw;
}

/** A link's host without `www.` / `m.`, or null when it is not a URL. */
export function linkHost(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^(www|m)\./, "") || null;
  } catch {
    return null;
  }
}

/** The platform a link points at, judged from its host alone — for a run the
 *  server has not classified yet (a link run that failed before any metadata
 *  arrived). `other` for any other host; null when it is not a URL. */
export function platformFromUrl(url: string | null | undefined): RunPlatform | null {
  const host = linkHost(url);
  if (!host) return null;
  const is = (domain: string) => host === domain || host.endsWith(`.${domain}`);
  if (is("youtube.com") || is("youtu.be")) return "youtube";
  if (is("instagram.com")) return "instagram";
  if (is("tiktok.com")) return "tiktok";
  return "other";
}
