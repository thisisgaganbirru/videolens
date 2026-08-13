# Results view

Renders a completed run's analysis across four tabs: Notes (markdown), Summary, Transcript, On-screen text.

**Files**
- `frontend/components/ResultsView.tsx` — everything (purely presentational, takes `result: VideoAnalysis` and an optional `sourceMetadata?: SourceMetadata | null` as props; no hook needed since it holds no cross-component state).

**Transcript/on-screen-text tabs**: render as a timestamped timeline (`TimelineView`) when segment data (`transcript_segments`/`screen_text_segments`) is present, falling back to the flat `transcript`/`screen_text` string otherwise (both are always returned by the backend, but segments are the richer view when Gemini provides them).

**Actions**: copy the current tab's content to clipboard and share it (native
`Share` API via Capacitor on native platforms, `navigator.share` on web where
supported — hidden entirely if neither is available). **Download report
(.md)** builds one complete Markdown document containing the generated title,
available source metadata and caption, summary, notes, timestamped transcript,
and timestamped on-screen text. Older results without timestamp segments fall
back to their flat transcript/on-screen-text fields. The filename is slugified
from the generated title. Report generation is local and does not make another
AI request.

**Source card**: URL-based results show platform metadata above the tabs. The
link to the original post is grouped directly beneath the platform badge, with
the uploader alongside that platform/link column, followed by the caption and
available engagement counts.

**Platform icons**: the platform badge shows each site's official logo glyph
next to the name, via `PLATFORM_ICONS` (keyed by lowercased
`metadata.platform`, i.e. yt-dlp's `extractor_key`) mapping to static SVGs in
`frontend/public/brand/`. Only Instagram and YouTube are included — both
downloaded directly from their official brand-resource pages (Meta Brand
Resource Center's `IG_brand_asset_pack_2023.zip`, Google's
`developers.google.com/static/youtube/images/youtube-icons-2x.png` page) and
minified with `svgo` (~1.7 KB and ~0.4 KB respectively). TikTok is
deliberately excluded: their brand guidelines require prior written
permission to use their logo, unlike Instagram/YouTube which permit
unmodified-logo attribution use, so TikTok results just show the plain text
label. A platform with no entry in `PLATFORM_ICONS` (including TikTok) simply
renders no icon. It is a full-width responsive glass card using
the raised-surface token's 30% background alpha; only the background is
translucent, while its text and controls remain fully opaque. Padding tightens
on small screens and long uploader names truncate safely. Its premium hierarchy
uses a creator monogram, optional source title, a readable caption measure,
icon-led engagement data with tabular numerals, and the source date when
available. The surrounding `ResultsView` is an unframed content section,
making this source module the single card containment layer in the
completed-result view.

**Known issue**: none identified.

**Tests**: none (see `run-analysis-hook.md`).
