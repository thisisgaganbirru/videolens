# Results view

Renders a completed run's analysis across four tabs: TL;DR (`summary`), Notes
(`markdown`), Transcript, On-Screen.

> **Superseded in part by the editorial Phase 2 rebuild (2026-11-01)** — see
> "Editorial Phase 2 layout" below. Tab order is unchanged and **TL;DR is still
> the default** (Phase 2 briefly opened on Notes; the owner reverted it). The
> labels are "TL;DR / Notes / Transcript / On-screen", drawn as underlined tabs.
> The four-column grid described under "Tab layout" is gone.

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

## Editorial Phase 2 layout (2026-11-01)

Built against `design/shots/Results.png`, `ResultsDark`, `ResultsWeb`,
`ResultsMobile` and `ResultsTranscript`.

- **Two columns at ≥ 56rem** (laid out by `HomeScreen.tsx`, which owns `.source-panel` and `.result-card`): a source column (`.source-panel`: platform chip,
  title, channel, stats, caption disclosure) on the left and the result card on
  the right. Below that the source collapses to a toggle above the card.
- **Result card** (`.result-card`): serif title band with copy / share icon
  actions, then the tab row, then the panel, then "Download .md" (text button,
  no icon — the boards draw none).
- **Tabs**: TL;DR / Notes / Transcript / On-screen in that order; **TL;DR opens
  by default** (`DEFAULT_TAB = "summary"`, owner's call; the boards show Notes
  selected, which is a deliberate deviation now). Roving `tabindex` with Arrow /
  Home / End, `role="tablist"`/`"tab"`/`aria-selected` unchanged.
- **Underlined tabs, not a segmented control** (owner spec, 2026-11-01):
  15px labels, weight 600 on every tab; selected = ink text plus a 2px
  `--color-accent` underline (#1A7F37 light / #3FB950 dark); others =
  `--color-muted`, ink on hover. Each tab ≥ 44px tall; gap 28px, 20px below
  36rem. The row is one 1px `--color-rule` line across its full width and the
  underline overlaps it by exactly 1px. Focus: 2px accent outline, 2px offset.
  The row scrolls sideways on narrow phones (measured: scrolls at 320, fits at
  390), never wraps, and never overflows the page.
  *Why not `margin-bottom: -1px` over a border:* the row is a scroll container,
  which clips its children, so that overlapping pixel was being cut off (the
  "no underline" the owner saw). The rule is now the list's own background,
  positioned on its content box's bottom edge, and the list carries 4px of
  padding cancelled by a -4px margin so neither the underline nor the focus
  ring's offset can be clipped.
- **Serif reading measure**: `.prose-serif` is Newsreader at 1.125rem
  (1.1875rem ≥ 48rem) on `--measure-serif: 36rem`. Measured at 1280: ~74
  characters per line in Notes, ~69 in transcript rows. The board's column is
  wider (~615px, >80 cpl); the measure was held to 65–75 on purpose.
- **Transcript**: search field (pill input, no leading icon — matching the
  board), a "Timestamps" switch (`role="switch"`; off sets `data-times="off"`
  and hides the time column), `<mark>` on hits, and an empty state "Nothing in
  this transcript matches …" with a Clear search button.
- **Caption-only runs**: the completeness note and the replacement on-screen
  empty line described above are unchanged, just re-tokened.

**Deliberate deviations**
- Notes blockquotes stay unlabelled (same accent-soft panel, no label): they
  are whatever the model's markdown quoted. The "Key takeaway" label belongs
  only to the TL;DR's first sentence, below.
- The platform icon stays in the source chip (official glyphs, see
  "Platform icons" above); the board shows a text-only chip.

**Key takeaway (owner decision 2026-11-01).** The TL;DR tab renders the
summary's first sentence as a `figure.takeaway` with a small-caps
`figcaption.takeaway-label` "Key takeaway" (accent-strong on accent-soft, the
Notes blockquote's panel), then the rest as a serif paragraph that keeps its
line breaks. The split is `splitTakeaway()` in `components/takeaway.ts` (pure):
the first line if the model wrote lines, else its first sentence via
`Intl.Segmenter` (`en-u-ss-standard`) plus a merge pass over an abbreviation
list (e.g., i.e., Dr., U.S., a.m., single initials), with a regex fallback for
WebViews without `Intl.Segmenter`. Decimals ("3.5%", "$4.99") never split.
Edge cases: one sentence gives the block alone; an empty or whitespace summary
gives no block and "No summary was generated."; an ambiguous abbreviation at a
real sentence end ("6 p.m. Then rest.") stays joined, which shows a longer
takeaway rather than a broken one. The downloaded .md report is unchanged (the
whole summary under `## Summary`).

**On-screen tab, text only (design/newshots/ResultsOnScreenText.png +
ResultsOnScreenTextMobile.png).** `OnScreenView` replaced the token-restyled
`TimelineView` (deleted, with its `.ocr-tag` pill). A muted `.t-intro` line
("Text found in the video frames, with the time it appears."), then
`ol.t-list.t-list--screen`: per segment the start time (accent, 600) in a
3rem column (3.75rem from 48rem) and the text in serif 1.125rem / 1.65,
keeping the model's line breaks so a card listing three items stays three
lines; hairlines between rows, 40rem measure. No segments but a
`screen_text` string: the intro plus the text alone (`.screen-text`). Nothing
at all: just the empty message (the caption-only wording on `captions_only`
runs). The downloaded report's On-screen section is unchanged.

**Verified** with Playwright against the dev server (backend faked): Results
1280×1098 (section 964/964), ResultsDark, ResultsWeb 390, ResultsMobile 390
app shell, ResultsTranscript 846/846; keyboard End lands on On-screen; search
with timestamps off; empty search; caption-only note. No page errors, no
horizontal overflow, no document scroll.

## Share, Download and Copy (refinement 1, #12/#13)

- **Download .md on Android did nothing.** A blob `<a download>` click is
  dropped by the Capacitor WebView (no download listener). Exports now go
  through `DocumentExporter` (`domain/ports.ts`) →
  `infrastructure/documentExporter.ts` → `application/useResultExport.ts`; the
  component no longer imports Capacitor. On Android "Download .md" opens the
  system share sheet with the whole report as text (`@capacitor/share`, already
  installed; dialog "Save notes"), where Drive, Files, notes apps or mail take
  it. In a browser it is the same blob download as before (verified:
  `test-video.md`, full report).
- **A real `.md` file on Android (refinement 2, #1).** Supersedes the text
  share above. `@capacitor/filesystem@^8.1.5` is installed; native save writes
  `exports/<slug>.md` (slug capped at 80 chars) into `Directory.Cache` as
  UTF-8, then calls `Share.share({ title, files: [uri], dialogTitle: "Save
  notes" })`, so the sheet carries a file and offers Save to Files, Drive and
  the like. The share plugin turns the `file://` URI into a content URI through
  the app's FileProvider; `res/xml/file_paths.xml` already has `<cache-path
  name="my_cache_images" path="." />`, which covers the cache root and every
  folder under it, so **no native change was needed**. If the write fails (for
  example an APK built before `cap sync` registered the plugin) save falls back
  to the old text share, so the button is never dead. The web blob download is
  unchanged. **Needs `cap sync`** before an APK has the plugin.

## Source card for uploaded files (refinement 2, #6)

The server keeps no file name (`backend/app/interface/api/schemas.py`: "the
filename itself is never kept"); the run detail does return
`duration_seconds` for uploads. So:

- `HistoryRecord.file_name` (new, optional) is written by `recordSubmitted`
  from the picked `File.name`. It stays in IndexedDB, never sent anywhere.
- `useAnalysisRun` exposes `durationSeconds` (from each run response, or the
  History record on reopen) and restores `sourceName` from `record.file_name`.
- `FileSourceCard` (`components/ResultsView.tsx`): a chip ("Video file" /
  "Audio file" by extension, else "Uploaded file"), the file name (wraps
  anywhere, `.source-card__file-name`) and a ruled footer "Duration m:ss"
  (`formatDuration` from `components/history.ts`). `HomeScreen` renders it when
  a file run has a name or a duration; the phone pill reads "Source: <name>". A
  file run with neither keeps the old "No source details" note.
- Uploads from before this change, and runs imported from the server, have no
  name; they show the duration alone.
- **Share sends the whole report**, the same string as Download (verified
  byte-identical in a browser via a `navigator.share` spy), labelled "Share
  notes". It used to send only the active tab.
- **Copy is unchanged in scope:** it copies the active tab's text (labelled
  "Copy this tab"). It now swallows a clipboard rejection instead of throwing,
  and shows no tick then.
- `canShare` moved from a set-state-in-effect to `useSyncExternalStore`, which
  removes one of the pre-existing lint errors.

## Copy says what it copies (refinement 4, RES-05)

Behaviour unchanged (Copy = active tab, Share and Download = whole report);
the labels now say so. `COPY_NOUN` maps each tab to a noun: Copy's
`aria-label`/`title` are "Copy TL;DR" / "Copy notes" / "Copy transcript" /
"Copy on-screen text", following the active tab; after copying they become
"<Noun> copied". The confirmation is also visible, since a touch screen has no
tooltip: `.copy-flash`, a small ink label under the button for the tick's two
seconds, absolutely positioned (nothing moves), plus an always-mounted
`role=status` in `.copy-wrap` that announces "<Noun> copied to the clipboard.".
Share's label is now "Share all results" (was "Share notes", which collided
with "Copy notes"). There is no other copy-all affordance in the app.
Verified per tab at 390x844 light/dark and 844x390: label, title, flash and
clipboard text match the tab. Share is not rendered in headless Chromium (no
`navigator.share`), so its new label is verified by source only.

## Refinement 6 (2026-11-02)

**RES-14, right-to-left results.** Every block of result text takes its
direction from its own content (`dir="auto"`): the title, the takeaway and
summary, transcript and on-screen text lines (and the plain-transcript
fallback), speaker labels, and in Notes every Markdown block (`h1`–`h4`, `p`,
`ul`/`ol`, `li`, `blockquote`, `th`/`td`). The Markdown renderers pass on only
what each element uses (`className`, `start`, and a GFM column's `style`), not
react-markdown's `node`. CSS moved to logical properties where it mattered:
`.prose-serif ul/ol` and `li` use `padding-inline-start`, and notes tables use
`text-align: start`. An Arabic note aligns right with its bullets on the right,
an English one in the same run stays left. Note: `dir="auto"` on a `ul` skips
children that carry their own `dir`, so the list element itself computes LTR;
each `li` is what flips, which is what places the marker.

## Platform names (refinement 9)

Source card, source toggle and the Markdown export's `Platform:` line print
`platformName(source_metadata.platform)` from `domain/platforms.ts`. yt-dlp's
extractor key used to print raw ("Source: Youtube"). The icon lookup uses
`platformKey`, which folds variants such as `YoutubeTab` onto their platform.
History's chip uses the same module, so one run is spelled one way everywhere.

## Narrow screens with large text (refinement 11, D-R10-2)

Web QA round 8 and device QA: at 320 and 360 px with the root font at 130%
the "Download .md" pill ran past the result card ("Download .m"; on a device
at 320/1.3 its right edge sat 7px past the card border), and the tab row,
whose scrollbar is hidden, cut "Transcript" off mid-word so it looked broken.

- **The action row wraps.** `.result-actions` is `flex-wrap: wrap` (with
  `min-width: 0; max-width: 100%`), so when copy, share and Download do not
  fit on one line Download drops to its own line and, on a phone, fills it.
  `.result-download` also gets `max-width: 100%; white-space: normal` as the
  last resort for a pill wider than the card on its own. `.result-title` got
  `min-width: 0; overflow-wrap: anywhere` so a long unbroken title cannot
  widen the band. At normal text sizes (390 and 1280, light and dark) the row
  is unchanged: Download beside the icons.
- **The tab row says it scrolls.** It still scrolls sideways rather than
  wrapping (an underlined tab row on two lines has no single rule to sit on).
  `.tab-list` is wrapped in `.tab-scroller`, and ResultsView tracks the list's
  scroll position (scroll listener + `ResizeObserver`, written straight into
  `data-more-start` / `data-more-end` on the wrapper, no React state). On
  whichever side has more, `.tab-more` shows a fade into `--color-surface`
  (solid for 70%) with a lucide chevron; tapping it pages the row by 70% of its
  width. The fade stops one rule-width above the bottom so the row's 1px rule
  is not covered. The chevrons are pointer helpers only (`aria-hidden`,
  `tabIndex=-1`); keyboard users move with the arrow keys as before. Choosing a
  tab calls `scrollIntoView({ inline: "nearest" })`, and
  `scroll-padding-inline: calc(2.75rem + 4px)` on the list makes the chosen or
  focused tab stop clear of the fades rather than under them. When the tabs
  fit, nothing shows. (This originally said "every width at the normal text
  size"; that was only checked at 390 and 1280 and is wrong, see refinement 12
  below: at 100% the row overflows below 360 px.)

Verified in `scratchpad\refine11\verify.py` at 320x640 and 360x640 (130%, light
and dark), 390 and 430 at 130%, and 390 / 1280 at 100% light and dark, with
`navigator.share` stubbed so all three actions render: no element of the card
past its edges, no page scroll, Download text unclipped and on its own row at
320/360, end chevron shown and paging both ways, Transcript and (via End)
On-screen fully clear of the fades, chevrons out of the a11y tree.

## Tab-row fades cover the whole edge (refinement 12)

Device QA at 320 CSS px: the fades and chevrons sat at x 37–81 and 239–283
while the tab list spans x 33–287, so about 4px of tab text (")" and "e")
showed past the outer edge of each chevron. Cause: `.tab-list` carries 4px of
padding cancelled by a -4px margin (room for the focus ring), so its
scrollport is 4px wider than `.tab-scroller` on each side, and the fades were
pinned to the wrapper's edges.

- `.tab-scroller` defines `--tab-bleed: 4px` (= the list's padding). The
  fades start at `-var(--tab-bleed)` and are `44px + var(--tab-bleed)` wide,
  so they cover the list's full edge and still end 48px in from the
  scrollport, where `scroll-padding-inline: 48px` stops a chosen tab.
- **Fade and chevron are fixed px now** (44px band, 18px icon; were 2.75rem
  and 1.125rem). They only appear with large text, and in rem they grew with
  it: 61px a side at 130%, 92px at 200%, which at 320 px left too little room
  between the two fades for any tab to stand clear.
- **Threshold, measured** (Chromium, Hanken Grotesk, 100% text): the row
  overflows and the end chevron shows at every width up to **359 CSS px** and
  never from **360 px** up (at 360 the list is 1px over, which is its own end
  padding, so no tab text is hidden and no chevron shows). At 320 px it is
  41px too wide. With larger text the threshold rises.
- Unchanged from refinement 11: chevrons page the row by 70%, are
  `aria-hidden` with `tabIndex=-1`, nothing shows when the tabs fit, and a
  chosen or focused tab scrolls clear of the fades.
- **320 px at 200% text — an emulation artefact, not a device limit**
  (corrected in refinement 13). Desktop Chromium, emulating 200% by setting
  the root font size, gives a ~182px list, where a middle tab (Transcript,
  138px) cannot fit between two 48px fades (86px band) and On-screen (140px)
  is 10px wider than the room beside one fade. **On the Android device the
  list is 254px wide and both land clear:** Transcript at x 101–239, On-screen
  at 143–283 (Android round 14). The device's font scale grows the text but
  not the rem lengths around it the way the emulation does, so the list keeps
  far more room. No geometric limit has been seen on a real device; the
  emulation case still degrades gracefully (the chosen label's start aligns
  clear of the start fade, the tail sits under the end fade with its chevron).

Verified in `scratchpad\refine12\verify.py`: 320 at 100/115/130/150/200% and
360 at 130/150%, light and dark — the 4px strip between wrapper and list edge
is pixel-identical to the card surface on both sides (no glyph), at scroll 0,
mid-scroll and the end; chevrons page both ways; Transcript, On-screen (End)
and TL;DR (Home) clear of the fades where geometry allows; no chevrons at
360/390/1280 at 100%; 1px threshold sweep 320–400.

## Changelog

- 2026-08-15 · frontend agent · ported ResultsView + SourceCard; de-boxed the source card, wired .disclosure and role=tabpanel, rebuilt SourceCard.preview with six states
- 2026-08-16 · main session · moved copy and share out of `.actions` into icon buttons in the top-right of a new `.result-head` title band, reusing the existing `.theme-toggle`/`.menu-toggle` icon-button treatment via `.icon-action`; download report stays a full-width button below, since it is the one action that ignores the active tab
- 2026-08-20 · main session · renamed the tabs (TL;DR/Notes/Transcript/On-Screen), moved TL;DR first and made it the default, and replaced the scrolling flex tab row with a four-column equal-width grid
- 2026-08-29 · frontend agent · surfaced `completeness`: added `.completeness-note` between the title band and the tabs, replaced the on-screen-text empty state on caption-only runs, and carried both into the downloaded report; nothing renders on `full`
- 2026-08-29 · frontend agent · reconciled the capability strip and caption-only note against the dev-side results-view restructure
- 2026-11-01 · frontend agent · editorial Phase 2: two-column source panel + result card, Notes as default tab, Newsreader serif on a 36rem measure (~74 cpl), transcript search/timestamps switch/empty state, icons dropped from Download and search to match the boards; deviations (no Key takeaway label, platform icon kept) and the deferred On-screen view recorded
- 2026-11-01 · frontend agent · results tabs rebuilt to the owner's underlined-tab spec (15px/600, 2px accent underline overlapping a full-width 1px rule, 28/20px gaps, 44px targets, 2px-offset focus ring, sideways scroll on narrow phones; rule moved to the list background so the scroll clip can't eat it); default tab reverted to TL;DR
- 2026-11-01 · frontend agent · TL;DR first sentence rendered as a labelled "Key takeaway" block (`components/takeaway.ts` splitter, abbreviation- and decimal-safe; one-sentence and empty summaries handled); Notes blockquotes stay unlabelled; report export unchanged
- 2026-11-01 · frontend agent · On-screen tab rebuilt text-only from design/newshots (OnScreenView: intro line, time | serif text rows, line breaks kept); TimelineView and .ocr-tag removed; the On-screen TODO(design) closed
- 2026-11-01 · frontend agent (Phase 4) · audit only, no change: TL;DR / Notes / Transcript / On-screen in that order, TL;DR default, 2px accent underline over the 1px rule — verified at 1366, phone web and phone app, light and dark
- 2026-11-01 · frontend agent (refinement 1) · Download/Share via DocumentExporter port: Android save opens the share sheet with the full report, Share sends the full report (was active tab), Copy stays per tab; filesystem plugin documented, not added
- 2026-11-02 · frontend agent (refinement 2) · Android "Download .md" writes a real `<slug>.md` to the cache (@capacitor/filesystem 8.1.5) and shares the file ("Save notes"), text-share fallback; FileProvider already covers the cache; file runs get FileSourceCard (name from IndexedDB `file_name`, duration from the run detail)
- 2026-11-02 · frontend agent (refinement 4) · Copy's accessible name, tooltip and a new visible confirmation name the active tab ("Copy transcript" / "Transcript copied"); Share relabelled "Share all results" (RES-05)
- 2026-11-02 · frontend agent (refinement 6) · RES-14 dir="auto" on every result text block incl. Markdown; logical padding/alignment
- 2026-11-02 · frontend agent (refinement 9) · source card, source toggle and Markdown export spell platforms through domain/platforms.ts ("YouTube", not yt-dlp's "Youtube")
- 2026-11-02 · frontend agent (refinement 11) · results header wraps at 320/360 with 130% text (Download drops to its own full row instead of overflowing the card); tab row keeps scrolling but shows an edge fade + chevron on the side with more, chevrons page the row, chosen tab scrolls clear of the fade (D-R10-2)
- 2026-11-02 · frontend agent (refinement 12) · tab-row fades/chevrons now start at the list's outer edge (`--tab-bleed`), so no tab text peeks past them; fade and chevron fixed px (44px/18px) instead of rem; corrected "nothing shows at normal size" to the measured threshold (chevron below 360 CSS px at 100%)
- 2026-11-02 · frontend agent (refinement 13) · corrected the R12 "geometric limit at 320/200%": it appears only in desktop Chromium's root-font emulation (~182px list); on the Android device the list is 254px and Transcript (101–239) and On-screen (143–283) both land clear. Doc only
