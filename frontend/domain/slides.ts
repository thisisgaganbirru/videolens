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
