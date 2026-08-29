# Results view

Renders a completed run's analysis across four tabs: Notes (markdown), Summary, Transcript, On-screen text.

**Files**
- `frontend/components/ResultsView.tsx` — everything (purely presentational, takes `result: VideoAnalysis`, an optional `sourceMetadata?: SourceMetadata | null`, and an optional `completeness?: AnalysisCompleteness` as props; no hook needed since it holds no cross-component state).
- `frontend/app/globals.css` — `.completeness-note`, in the results block directly above `.tab-list`.

**Transcript/on-screen-text tabs**: render as a timestamped timeline (`TimelineView`) when segment data (`transcript_segments`/`screen_text_segments`) is present, falling back to the flat `transcript`/`screen_text` string otherwise (both are always returned by the backend, but segments are the richer view when Gemini provides them).

**Actions**: copy the current tab's content to clipboard and share it (native
`Share` API via Capacitor on native platforms, `navigator.share` on web where
supported — hidden entirely if neither is available). **Download report
(.md)** builds one complete Markdown document containing the generated title,
available source metadata and caption, summary, notes, timestamped transcript,
and timestamped on-screen text. Older results without timestamp segments fall
back to their flat transcript/on-screen-text fields. The filename is slugified
from the generated title. Report generation is local and does not make another
AI request. A `captions_only` run adds the caveat below as a blockquote under
the title and carries the same replacement on-screen-text line — the report is
the copy that outlives the session, so exporting the uncorrected claim would
undo the fix.

## Caption-only runs (`completeness`)

`GET /api/runs/{run_id}` returns `completeness: "full" | "captions_only"`. The
salvage path (`docs/backend/run-processing.md` § Caption fallback) completes a
run from the subtitle track when every download route fails, so
`screen_text`/`screen_text_segments` come back empty — **because there were no
frames, not because the video had none**. Rendered as an ordinary success this
view asserted the opposite: a transcript, an empty on-screen-text tab, and a
reader who concludes the video had no on-screen text. The model is instructed
to open the summary with "Based on the caption track alone", but that is prose
carrying a structural fact and is easy to skim past.

Two corrections, and deliberately only two:

1. **`.completeness-note`, between the generated title and `.tab-list`.** It
   qualifies all four panels, so it belongs to the pane's fixed header rather
   than to any one of them — and in the `fixed` frame that header is the part
   that does not scroll away while the transcript is read. Reads: *"**Caption
   track only.** The video could not be downloaded, so this analysis read its
   captions and never saw a frame. Auto-generated captions mishear words, so
   the transcript is approximate."*
2. **The on-screen-text empty state.** `"No on-screen text was detected."`
   becomes `"No frames were analyzed — this run read the caption track only, so
   on-screen text was never looked for."` This tab is the exact place the false
   inference happens, which is why it gets its own words rather than relying on
   the header note.

Both strings are module constants shared with `buildMarkdownReport`, so the
screen and the exported file can't drift apart.

**Nothing renders at all on `full`.** Verified pixel-identical to before —
same rule the capability strip follows on a healthy deployment. The prop
defaults to `"full"` and the wire field is optional, so a backend older than
the fallback (which omits it) is silent too.

**The transcript tab gets nothing of its own**, even though caption-derived
transcripts are the less reliable ones. The header note is outside the scroller
and names *the transcript* explicitly in its second sentence; a second copy on
that tab would be the same sentence twice, which is the same call `.error-block`
already makes when it declines to repeat the gateway's message.

**Rejected: disabling the on-screen-text tab.** `.tab:disabled` exists and the
tab has nothing behind it, but disabling puts the explanation behind an
unreachable panel — the user then sees a greyed-out tab and cannot find out
why. Reachable tab, self-explaining panel.

**Severity ink is `--color-rule-2`, never `--color-danger`.** The run
succeeded; the salvage *is* the good outcome, and this is a qualifier on scope
much closer to `.cap-unverified`'s "read off configuration, not checked" than
to a fault. The palette still declares one danger token and no warning token.
For the same reason it is a plain `<p>`, not `role="alert"` and not a live
region: it arrives with brand-new content the user just navigated to, and read
in order it lands immediately after the title.

**History cannot show this.** `RunSummary` carries no `completeness` — the
backend does not return one from `GET /api/runs` — and deriving it client-side
would be inventing it. Marking caption-only runs in the history list needs the
backend to send the field there first; it is noted in `domain/entities.ts` so
the next reader doesn't fake it.

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
  the place if it needs centralising. `.completeness-note` sits directly below
  it and repeats the same `var(--space-md)` gutter rather than sharing one.
- **`.completeness-note` is tall on a narrow screen** — 4 lines / 116px at
  390px, 5 lines / 156px at 320px, all of it above the tabs and therefore above
  the panel content. Accepted: it only exists on the salvage path, `.pane` still
  scrolls, and shortening it means dropping either "never saw a frame" or the
  transcript caveat, which are the two things it exists to say.
- **The note's rule measures 2.22 (light) / 2.51 (dark) against `--color-paper-2`**,
  below the 3:1 non-text threshold. Same call as `.cap-unverified`'s outline and
  the same `--color-rule-2` token: the meaning is carried entirely by the text
  (10.14 / 10.39), so WCAG 1.4.11 does not apply to the rule.
- The rest of the view (source card, tabs, timeline) is still **not** visually
  verified beyond what the caption-only pass below happened to capture.

**Tests**: none (no frontend test runner — see `run-analysis-hook.md`). The
`completeness` rendering was verified with `npx tsc --noEmit`, `npm run build`,
and a Playwright/Chromium pass against `next start` with `/api/runs` mocked, at
1440x900, 768x1024, 414x896, 390x844, 375x667 and 320x640, light and dark:

| check | result |
|---|---|
| `completeness: "captions_only"` | 1 `.completeness-note` at 12.48px, on-screen-text panel reads "No frames were analyzed - ..." |
| `completeness: "full"` | 0 notes, panel reads "No on-screen text was detected.", header pixel-identical to before |
| field absent from the payload | identical to `full` - 0 notes, original empty message |
| contrast vs `--color-paper-2`, light / dark | body 10.14 / 10.39 · lead `<strong>` 16.99 / 16.14 · empty state 10.14 / 10.39 · rule 2.22 / 2.51 |
| horizontal overflow | 0px at all six widths, both themes, both branches |
| downloaded report | blockquote caveat under the title; on-screen-text section carries the replacement line |
| page errors | 0 across all 18 combinations |

Not tested on a physical device (emulation only) and never against a live
backend — the fixture is the payload shape in `docs/backend/run-processing.md`.

## Changelog

- 2026-08-15 · frontend agent · ported ResultsView + SourceCard; de-boxed the source card, wired .disclosure and role=tabpanel, rebuilt SourceCard.preview with six states
- 2026-08-29 · frontend agent · surfaced `completeness`: added `.completeness-note` between the title and the tabs, replaced the on-screen-text empty state on caption-only runs, and carried both into the downloaded report; nothing renders on `full`
