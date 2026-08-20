# Results view

Renders a completed run's analysis across four tabs: TL;DR (`summary`), Notes
(`markdown`), Transcript, On-Screen.

**Tab order and labels**: TL;DR opens by default and sits first because it is the
shortest read — the thing you want in front of someone the moment a run finishes.
Notes follows, then the two raw sources behind it. The labels are Title Case here
while the rest of the shell is lowercase, and "TL;DR" rather than "Summary"
deliberately: "summary" gave no signal that it was the *short* read, so it read as
a peer of Notes rather than a quicker version of it — the same confusion the
backend prompt now guards against (see `../backend/gemini-analysis.md`). Only the
`label` strings changed; the `key` values feed `result-tab-${key}` /
`result-panel-${key}` ids and the aria wiring, so they stay as they are. The four
panels remain in their original source order — only one is displayed at a time, so
DOM order among them is not observable.

**Tab layout**: `.tab-list` is a four-column grid (`grid-auto-flow: column` +
`grid-auto-columns: 1fr`), not the scrolling flex row it used to be. All four tabs
are visible at once on a phone, and each active underline spans an identical share
of the bottom rule. The auto-flow form avoids hard-coding the count in CSS as well
as in `TABS`. `.tab` keeps `white-space: nowrap` but drops to `0.25rem` of side
padding, since the grid column supplies the spacing and wide inline padding would
push the longest label out of a quarter-width column on a narrow screen.

**Files**
- `frontend/components/ResultsView.tsx` — everything (purely presentational, takes `result: VideoAnalysis` and an optional `sourceMetadata?: SourceMetadata | null` as props; no hook needed since it holds no cross-component state).

**Transcript/on-screen-text tabs**: render as a timestamped timeline (`TimelineView`) when segment data (`transcript_segments`/`screen_text_segments`) is present, falling back to the flat `transcript`/`screen_text` string otherwise (both are always returned by the backend, but segments are the richer view when Gemini provides them).

**Actions** are split by what they act on, which is why they sit in two
different places. **Copy** and **share** operate on *the tab you are looking
at*, so they live as icon buttons in the top-right of the `.result-head` title
band, which spans all four tabs; stacked under the panel they read as
belonging to the last panel's content. Share uses the native `Share` API via
Capacitor on native platforms and `navigator.share` on web, and is hidden
entirely when neither is available. Copy swaps its icon to a check and tints
it with `--color-accent` (`.icon-action[data-state="copied"]`) — the icon-only
equivalent of the old button relabelling itself "copied" — and its
`aria-label` changes with it so the confirmation is not colour-only.

`.icon-action` deliberately shares the `all: unset` base, 2.75rem touch
target, pill focus ring and 1.05rem glyph size with `.theme-toggle` /
`.menu-toggle` / `.menu-close` rather than defining a second icon-button
treatment.

**Download report (.md)** stays a full-width button in `.actions` below the
panel, because unlike the other two it ignores the active tab: it
builds one complete Markdown document containing the generated title,
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
- ~~The generated-title band above the tabs has no shared class~~ Fixed — it is
  `.result-head` now, which owns the gutter padding and the `flex-shrink: 0`
  the `<h2>` used to carry inline. The `<h2>` keeps only its typography.
- Not visually verified. The icon-action change and the tab grid were both
  typechecked (`npx tsc --noEmit`) and built (`npm run build`) clean, but no
  screenshot was taken — the title band's two-column layout and the four
  equal-width tab columns are unexercised visually. The tab widths in
  particular are worth a look on the narrowest phone: "Transcript" is the
  longest label and has to fit a quarter of the content width at 0.82rem.

**Tests**: none (see `run-analysis-hook.md`).

## Changelog

- 2026-08-15 · frontend agent · ported ResultsView + SourceCard; de-boxed the source card, wired .disclosure and role=tabpanel, rebuilt SourceCard.preview with six states
- 2026-08-16 · main session · moved copy and share out of `.actions` into icon buttons in the top-right of a new `.result-head` title band, reusing the existing `.theme-toggle`/`.menu-toggle` icon-button treatment via `.icon-action`; download report stays a full-width button below, since it is the one action that ignores the active tab
- 2026-08-20 · main session · renamed the tabs (TL;DR/Notes/Transcript/On-Screen), moved TL;DR first and made it the default, and replaced the scrolling flex tab row with a four-column equal-width grid
