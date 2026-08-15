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
renders no icon.

**Source card is deliberately unboxed** (Terminal redesign — see
`design-direction-terminal.md`). No border, no tint, no shadow: `.source-card`
is `background: transparent; padding: 0`. Only the results pane carries the
`--color-paper-2` tint. Two bordered tinted rectangles side by side read as a
PowerPoint slide, so structure comes from the single vertical hairline between
the columns instead. Do not re-box it. Its hierarchy is a creator monogram,
optional source title (two-line clamp), a readable caption measure with a
show-more disclosure, engagement counts, and the source date when available —
long uploader names truncate safely.

The description disclosure uses the **shared `.disclosure`**, not a BEM
variant: only the shared rule carries `all: unset`, the pointer cursor, and the
`[aria-expanded="true"]` chevron rotation. It needs `self-start`, since
`.disclosure` blockifies as a flex child and would otherwise stretch the full
column width as a hit target.

**Known issues**
- `.pull` (the mockup's pull-quote above the summary) is unused: `VideoAnalysis`
  has a single `summary: string` and no lead/quote field, and styling a whole
  multi-paragraph summary as a pull-quote would be wrong. Porting it faithfully
  needs a backend field that doesn't exist.
- `.ocr-tag` renders on *every* on-screen-text row, not selectively as the
  mockup shows — `ScreenTextSegment` has no field distinguishing an overlay from
  other on-screen text, so the mockup's one-tagged-row-of-three was sample
  variety, not data.
- The generated-title band above the tabs has no shared class; it's styled
  inline to align with `.tab-list`'s gutter. A `.result-title` class would be
  the place if it needs centralising.
- Not visually verified — no browser/screenshot tooling was available.

**Tests**: none (see `run-analysis-hook.md`).

## Changelog

- 2026-08-15 · frontend agent · ported ResultsView + SourceCard; de-boxed the source card, wired .disclosure and role=tabpanel, rebuilt SourceCard.preview with six states
