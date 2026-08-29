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
- `frontend/components/ResultsView.tsx` — everything (purely presentational, takes `result: VideoAnalysis`, an optional `sourceMetadata?: SourceMetadata | null`, and an optional `completeness?: AnalysisCompleteness` as props; no hook needed since it holds no cross-component state).
- `frontend/app/globals.css` — `.completeness-note`, in the results block between `.result-head` and `.tab-list`.

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

1. **`.completeness-note`, between the `.result-head` title band and
   `.tab-list`.** It qualifies all four panels, so it belongs to the pane's
   fixed header rather than to any one of them — and in the `fixed` frame that
   header is the part that does not scroll away while the transcript is read.
   It is a *sibling* of `.result-head`, not a child: that band is a two-column
   row (title left, copy/share icons right), and a full-width note has no
   column there. Reads: *"**Caption
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
- ~~The generated-title band above the tabs has no shared class~~ Fixed — it is
  `.result-head` now, which owns the gutter padding and the `flex-shrink: 0`
  the `<h2>` used to carry inline. The `<h2>` keeps only its typography.
  `.completeness-note` sits directly below the band and repeats the same
  `var(--space-md)` gutter rather than sharing one, so band, note and tab row
  hang off one left edge by agreement rather than by inheritance.
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
  verified beyond what the caption-only pass below happened to capture — and
  that pass predates the title band and the tab grid (see the note under
  **Tests**).
- The title band's two-column layout and the four equal-width tab columns are
  typechecked and built clean but unexercised visually. The tab widths in
  particular are worth a look on the narrowest phone: "Transcript" is the
  longest label and has to fit a quarter of the content width at 0.82rem.
- **The note and the icon actions have never been seen on screen together.**
  `.result-head` reserves its right-hand column for two 2.75rem icon buttons
  pulled up into the band's own padding; `.completeness-note` lands directly
  under the whole band. Nothing in the CSS makes them collide, but on a narrow
  screen a long title wrapping beside the icons with a 4-line note under it is
  the tallest this header can get, and that has not been measured.

**Tests**: none (no frontend test runner — see `run-analysis-hook.md`).

> **The browser pass below predates the 2026-08-16/08-20 restructure.** It was
> run when the title was a bare inline-styled `<h2>` and `.tab-list` was a
> scrolling flex row. The assertions about the note itself — present on
> `captions_only`, absent on `full` and on a payload with no field, its
> contrast, and the downloaded report's contents — do not depend on the
> header's layout and still hold. The *measured* figures (note height, zero
> horizontal overflow) were taken against the old header and have not been
> re-measured against `.result-head` + the four-column grid. Treat those as
> indicative, not current; re-running this pass is the most useful
> verification anyone can do on this view.

The `completeness` rendering was verified with `npx tsc --noEmit`,
`npm run build`, and a Playwright/Chromium pass against `next start` with
`/api/runs` mocked, at
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
- 2026-08-16 · main session · moved copy and share out of `.actions` into icon buttons in the top-right of a new `.result-head` title band, reusing the existing `.theme-toggle`/`.menu-toggle` icon-button treatment via `.icon-action`; download report stays a full-width button below, since it is the one action that ignores the active tab
- 2026-08-20 · main session · renamed the tabs (TL;DR/Notes/Transcript/On-Screen), moved TL;DR first and made it the default, and replaced the scrolling flex tab row with a four-column equal-width grid
- 2026-08-29 · frontend agent · surfaced `completeness`: added `.completeness-note` between the title band and the tabs, replaced the on-screen-text empty state on caption-only runs, and carried both into the downloaded report; nothing renders on `full`
- 2026-08-29 · frontend agent · reconciled the capability strip and caption-only note against the dev-side results-view restructure
