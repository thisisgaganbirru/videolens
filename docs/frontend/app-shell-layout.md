# App shell layout

The single centered "glass card" shell every tab renders inside.

**Files**
- `frontend/components/HomeScreen.tsx` — the shell (`<main className="surface-panel ...">`) plus the header nav and all five tab panels.

**Responsive card sizing**: the card grows on wider viewports rather than staying a fixed width — `max-w-4xl` by default, `lg:max-w-6xl xl:max-w-7xl` on desktop, `max-h-[94dvh]` (`lg:max-h-[97dvh]`) — with a shrinking outer margin (`p-3 sm:p-5 md:p-6`) around it so it still reads as a centered card, not edge-to-edge full-bleed. Reading-heavy content inside stays capped at `max-w-prose` (`ResultsView`'s markdown/summary/transcript/on-screen-text panes) so text lines don't stretch uncomfortably wide just because the outer card did — the card growing and the text column growing are deliberately decoupled. `HistoryPanel`/`VersionLogPanel`'s existing `max-w-2xl` wrappers follow the same idea and predate this.

**Results two-column layout (desktop only)**: once a run is `complete`, the Analyze tab's content area (`HomeScreen.tsx`) becomes a `lg:grid lg:grid-cols-[3fr_7fr]` row — a left sidebar (30%: `SourceCard` + "Analyze another file") and `ResultsView` on the right (70%), instead of everything stacked in one column. `ResultsView`'s own inline `SourceCard` is hidden at `lg:` (`lg:hidden` wrapper) since the sidebar shows it instead; below `lg`, the sidebar div is `hidden` entirely and `ResultsView` renders exactly as it always has (its own `SourceCard` inline, "Analyze another file" back at the bottom). Below `lg` nothing about this changes from before.

To fit "the whole result on one screen" at `lg:`, `ResultsView`'s active tab content pane switches from a fixed `max-h-[36rem]` to `lg:flex-1 lg:min-h-0 lg:max-h-none` — it fills whatever vertical space remains in the (now height-bound, `lg:h-full`) card rather than a fixed height, with its own `overflow-y-auto` scrolling only that pane if content is longer than the available space. This relies on the whole ancestor chain (`HomeScreen`'s `<main>` → tab-content wrapper → analyze-tab column → two-column row → `ResultsView`'s `<section>`) having a real (not just auto) height at `lg:`, via flexbox/grid's default `align-items: stretch` plus explicit `lg:h-full`/`lg:min-h-0` at each level — `min-h-0` specifically overrides flexbox's default `min-height: auto`, which is what would otherwise force the pane to grow to fit its content instead of scrolling internally.

**Known issue**: none identified. Not verified with a real browser screenshot (no browser tool available this session) — verified via `tsc --noEmit` and reasoning through the flex/grid height-propagation chain; ask for visual confirmation after any change here.

**Tests**: none (see `run-analysis-hook.md`); verified via `tsc --noEmit`.
