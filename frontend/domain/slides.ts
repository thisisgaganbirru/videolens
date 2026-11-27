import type { PostSlide } from "./entities";

/* A multi-slide post's slide pictures (2026-11-27). Pure, no React, no DOM.

   The gateway casts the run response rather than validating it, so `slides`
   is read here before anything uses it: a malformed item is dropped, a
   thumbnail that is not an image data URI becomes null (the view then draws
   its neutral placeholder rather than a broken image), and the list comes
   back in slide order with one entry per slide. */

/** The response's `slides`, cleaned; null when there is nothing usable. */
export function readSlides(raw: unknown): PostSlide[] | null {
  if (!Array.isArray(raw)) return null;
  const bySlide = new Map<number, PostSlide>();
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const { slide, kind, thumbnail } = item as Record<string, unknown>;
    if (typeof slide !== "number" || !Number.isInteger(slide) || slide < 1) continue;
    if (bySlide.has(slide)) continue;
    bySlide.set(slide, {
      slide,
      kind: kind === "video" ? "video" : "image",
      thumbnail: typeof thumbnail === "string" && /^data:image\/[a-z+.-]+;base64,/i.test(thumbnail) ? thumbnail : null,
    });
  }
  if (bySlide.size === 0) return null;
  return [...bySlide.values()].sort((a, b) => a.slide - b.slide);
}

/** What a run is known to be, for naming it. Every field optional: reels,
 *  uploads and older History entries have none of them. */
export interface PostFacts {
  slides?: ReadonlyArray<{ kind: string }> | null;
  slideCount?: number | null;
}

/* 2026-11-27. yt-dlp titles an untitled Instagram item "Video by <user>"
   even when it is a photo or a carousel, and the source card and History
   echo it. Display only: the stored metadata keeps yt-dlp's string. A
   one-photo post reads "Photo by", a multi-slide post (or one slide of
   unknown kind) "Post by". A video, a single video slide, any other title,
   and a run with no slide facts (every older entry) keep the title as is. */
export function sourceTitle(title: string, facts: PostFacts = {}): string {
  const match = /^Video by ([\s\S]+)$/.exec(title);
  if (!match) return title;
  const slides = facts.slides ?? [];
  const count = Math.max(slides.length, facts.slideCount ?? 0);
  if (count >= 2) return `Post by ${match[1]}`;
  if (count === 1) {
    if (slides.length === 1) return slides[0].kind === "image" ? `Photo by ${match[1]}` : title;
    return `Post by ${match[1]}`;
  }
  return title;
}
