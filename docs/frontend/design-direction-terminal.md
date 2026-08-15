# Terminal design direction (locked mockup)

**Status: implemented.** `frontend/` now ships this direction — see
`app-shell-layout.md` for the shell, and the per-feature docs for each view.
This file remains the authority on *why* the design is what it is; where the
implementation deliberately diverges from the mockup, that's recorded under
"Known issues" below and in `mem/20260815-terminal-redesign-implementation.md`.

A self-contained HTML mockup of the whole app in the "Terminal" visual
direction, covering every screen at both desktop and phone width. It is a
**design reference, not shipped code** — nothing in `frontend/` imports it and
no app behaviour depends on it. It exists so the redesign can be reviewed and
implemented against a fixed target instead of a moving one.

**Files**
- `docs/frontend/mockups/terminal-redesign.html` — the entire mockup: inline
  `<style>`, markup, and a small vanilla-JS block for tab/menu/theme state. No
  build step, no external requests; open it directly in a browser.

## What's locked

**Palette** — OKLCH tokens on `:root` (light, the default), overridden by
`:root[data-theme="dark"]`. The rule that matters: every ink and paper token is
near-neutral (chroma below ~0.015) and green appears **only** as
`--color-accent`. Tinting the text green in both themes is what made an earlier
pass read as generated "hacker terminal" slop.

**Type** — a single system monospace stack for both `--font-display` and
`--font-body`. Single-face is deliberate here, not a missing pairing. Reading
sizes are a notch smaller than a serif would need (prose `0.86rem`) because
mono sets wider per character.

**Structure** — the shell is locked to one viewport (`100dvh`, `overflow: clip`)
as a flex chain: nav band, active view (`flex: 1`), footer band. Heights are
*measured*, never computed by subtracting a guessed constant from `100vh`.

- Nav: floating pill, translucent + `backdrop-filter`, pulled half a rem past
  the shell gutter so it sits proud of the content.
- Analyze: two ruled columns at `3fr / 7fr` (matching the live app's
  `lg:grid-cols-[3fr_7fr]`), separated by a single vertical hairline. Neither
  column is a bordered card — structure comes from rules and alignment. Only
  the results pane carries a `--color-paper-2` tint (`.surface`).
- History / API key: single column, same micro-label + `.surface` language.
- Home / processing / failed: centred single column, no panel.
- Footer: compact bar mirroring `HomeScreen.tsx:181` (wordmark left, legal
  links right, hairline above).

**Responsive model** — `@container` queries measuring `.viewport`, **not**
`@media` queries measuring the window. This is what lets the footer's
demo-only `WEB | MOBILE` switch constrain `.viewport` to 390px and have the
real mobile layout appear, rather than maintaining a second mockup.

**Mobile specifics** — nav collapses to wordmark · menu · theme, with the tabs
moving into a left drawer over a dimmed scrim. The Analyze source column
becomes a disclosure, collapsed by default so results sit at the top; collapsed
keeps a fixed frame with only the results pane scrolling, expanded reverts to
normal page scroll. 44px touch targets via `pointer: coarse`, safe-area insets
on the shell, hover-only affordances made permanent on touch.

## Fidelity to the real app

Checked against source rather than invented:

- The source card mirrors `SourceCard` (`frontend/components/ResultsView.tsx:209`)
  section for section — origin row, creator block with the title nested under
  the uploader, description with a Show more/less disclosure, stats footer with
  labelled counts and upload date.
- History rows use only what `RunSummary` carries (`frontend/domain/entities.ts:53`):
  `run_id`, `status`, `title`, `created_at`. Day grouping and the short-hash run
  ID are derived from those; there is no platform, duration or thumbnail because
  the API doesn't return them.
- The footer matches `HomeScreen.tsx:181-187`.

## Known issues

- **Six nav tabs are a mockup convenience.** The real app has three
  (analyze / history / api key). Home and Analyze are two states of the Analyze
  tab, and processing/failed are run states, not destinations. Don't port the
  nav as-is.
- **Responsive rules are desktop-first** — `max-width` container queries. This
  is a deliberate deviation (the mockup grew outward from the desktop layout)
  and is stamped as such in the file. A real implementation should invert them
  to `min-width`. *(Done — the shipped CSS is mobile-first `@media`, and drops
  `@container` entirely since the real app has no web/mobile demo switch.)*
- **`env(safe-area-inset-*)` is inert without `<meta name="viewport"
  content="...viewport-fit=cover">`.** The CSS is correct; the meta tag has to
  be added wherever this lands.
- **The processing → analyze transition is a 2.8s demo timer.** The failed
  branch is reachable only via its own tab; swapping it in is a one-word change
  flagged in the JS.
- Not verified on a physical device — only in-browser at 390px and desktop.

## Tests

None; it's a static reference file with no imports and no build step.
