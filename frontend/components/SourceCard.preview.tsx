/* Hallmark · component: source-card · genre: editorial · theme: Terminal
 * states: rich · long-caption (clamp + disclosure) · no-uploader · no-stats ·
 *         unknown-platform (no brand glyph) · minimal
 * Dev-only harness. Each state is wrapped in the real shipping chrome from
 * HomeScreen (`.left-col` > `.col-label` + `.source-frame` > `.source-body`),
 * so the card renders under ship conditions — bare, unboxed, with the single
 * hairline under `.source-body` doing the separating. Not routed: mount it
 * temporarily under app/ to eyeball changes, then remove.
 */

import { SourceCard } from "./ResultsView";
import type { SourceMetadata } from "@/domain/entities";

/* Only fields SourceMetadata actually carries (frontend/domain/entities.ts) —
   no duration, thumbnail, or anything else the payload never returns. */
const PREVIEW_STATES: Array<{ label: string; metadata: SourceMetadata }> = [
  {
    label: "Rich — every field populated",
    metadata: {
      platform: "YouTube",
      source_url: "https://www.youtube.com/watch?v=preview",
      title: "How Ground-Glass Light Tables Are Made",
      uploader: "Grit & Ground Optics",
      uploader_url: "https://www.youtube.com/@preview",
      description:
        "Three grit stages — 80, 220 and 600 — each changing the falloff of a projected grid.",
      upload_date: "20260809",
      view_count: 18400,
      like_count: 1200,
      comment_count: 86,
    },
  },
  {
    /* Past the 160-char threshold, so the disclosure renders and the caption
       clamps to three lines until it is expanded. */
    label: "Long caption — clamps to 3 lines, show more/less",
    metadata: {
      platform: "Instagram",
      source_url: "https://www.instagram.com/p/preview/",
      title: "caveman mode explainer",
      uploader: "Shirin Khosravi Jam",
      uploader_url: "https://www.instagram.com/preview/",
      description:
        "Ground glass gets its even, directionless diffusion from sandblasting followed by a fine abrasive slurry rubbed in by hand — three grit stages, 80, 220 and 600, each changing the falloff of a projected grid.\n\nThe closing segment covers annealing: panels held at 545°C for two hours, then cooled over eight to avoid the internal stress that cracks glass under a hot projector lamp.",
      upload_date: "20260810",
      view_count: 940000,
      like_count: 93000,
      comment_count: 2000,
    },
  },
  {
    /* No uploader → the whole creator block (monogram, name, nested title)
       drops out, and the origin row sits straight above the caption. */
    label: "No uploader — creator block absent",
    metadata: {
      platform: "YouTube",
      source_url: "https://www.youtube.com/watch?v=preview2",
      title: "Anneal cycle, unattributed re-upload",
      description: "Short clip, no creator attribution returned by the extractor.",
      upload_date: "20260714",
      view_count: 312,
    },
  },
  {
    /* Every count null and no upload_date → the stats footer, and its hairline,
       drop out entirely rather than rendering zeroes. */
    label: "No stats, no date — footer absent",
    metadata: {
      platform: "Instagram",
      source_url: "https://www.instagram.com/reel/preview/",
      uploader: "Elin Vasquez-Moreau",
      uploader_url: "https://www.instagram.com/preview2/",
      description: "Caption present, engagement counts withheld by the source.",
    },
  },
  {
    /* TikTok is deliberately absent from PLATFORM_ICONS (brand guidelines
       require prior written permission), so this falls back to plain text. */
    label: "Unknown platform — no brand glyph",
    metadata: {
      platform: "TikTok",
      source_url: "https://www.tiktok.com/@preview/video/1",
      uploader: "hand.finished.optics",
      description: "Falls back to the plain platform-name label with no icon.",
      like_count: 4300,
      comment_count: 51,
    },
  },
  {
    label: "Minimal — platform and URL only",
    metadata: {
      platform: "YouTube",
      source_url: "https://www.youtube.com/watch?v=preview3",
    },
  },
];

export default function SourceCardPreview() {
  return (
    <main className="mx-auto flex w-full max-w-[26rem] flex-col gap-[var(--space-xl)] px-[var(--space-sm)] py-[var(--space-xl)]">
      {PREVIEW_STATES.map((preview) => (
        <section key={preview.label} className="flex flex-col gap-[var(--space-sm)]">
          <p className="card-label">{preview.label}</p>
          <div className="left-col" data-collapsed="false">
            <p className="col-label">Source</p>
            <div className="source-frame">
              <div className="source-body">
                <SourceCard metadata={preview.metadata} />
              </div>
              <button type="button" className="reset-link">
                analyze another file
              </button>
            </div>
          </div>
        </section>
      ))}
    </main>
  );
}
