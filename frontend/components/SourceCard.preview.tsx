/* Hallmark · source-card content preview: rich · sparse */

import { SourceCard } from "./ResultsView";
import type { SourceMetadata } from "@/domain/entities";

const RICH_SOURCE: SourceMetadata = {
  platform: "Instagram",
  source_url: "https://www.instagram.com/",
  uploader: "Shirin Khosravi Jam",
  description:
    "Went in caveman mode for this one 🤣 hope it was useful!\nIn the Reel, I explained it in the simplest way.",
  upload_date: "20260810",
  like_count: 93000,
  comment_count: 2000,
};

const SPARSE_SOURCE: SourceMetadata = {
  platform: "YouTube",
  source_url: "https://www.youtube.com/",
};

export default function SourceCardPreview() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-10 px-4 py-12">
      {[
        { label: "Rich metadata", metadata: RICH_SOURCE },
        { label: "Sparse metadata", metadata: SPARSE_SOURCE },
      ].map((preview) => (
        <section key={preview.label} className="flex flex-col gap-3">
          <p className="text-sm font-semibold text-[var(--color-muted)]">{preview.label}</p>
          <SourceCard metadata={preview.metadata} />
        </section>
      ))}
    </main>
  );
}
