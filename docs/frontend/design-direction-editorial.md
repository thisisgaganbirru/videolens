# Editorial design direction (current)

**Status: Phases 1 and 2 implemented.** Phase 1: tokens, fonts, app shell,
bottom tab bar, More sheet. Phase 2: the Analyze tab's core flow — intake,
progress filmstrip, results — rebuilt structurally against the shots (see
`upload-form.md`, `run-status-pipeline.md`, `results-view.md`). Supersedes
`design-direction-terminal.md`. Phases 3–5 (History, API key, Releases, legal
pages, free-run banner, thumbnails, landing) are not done; those views render
with the shared component classes on the new tokens.

Source of truth for the look is the owner's handoff in `design/`
(`design-handoff.md`, `tokens.css`, `shots/*.png`). This doc records how it was
mapped into `frontend/` and every value that had to be decided because the
handoff did not specify it.

**Files**
- `frontend/app/tokens.css` — every token; light on bare `:root`, dark under `:root[data-theme="dark"]`. No `prefers-color-scheme` block (light is the first-visit default).
- `frontend/app/layout.tsx` — `next/font` loading and the two pre-paint scripts (theme, shell mode).
- `frontend/components/theme.ts` — `THEME_COLOR` (`#F6F4EE` / `#0E100F`).
- `frontend/components/shell.ts` — `ShellMode`, `SHELL_STORAGE_KEY`.
- `frontend/app/manifest.ts`, `frontend/capacitor.config.ts` — paper colour for splash/manifest.

## Palette

Warm paper, near-black ink, one green accent. Values are the handoff's, verbatim,
except where marked *proposed* (the handoff had no dark value for them).

| Token | Light | Dark |
|---|---|---|
| `--color-paper` | `#F6F4EE` | `#0E100F` |
| `--color-surface` / `--color-tint` | `#FFFFFF` / `#EDEAE0` | `#171A18` / `#212522` |
| `--color-ink` / `--color-muted` | `#15161A` / `#5E5F68` | `#ECEDE8` / `#9A9E97` |
| `--color-accent` | `#1A7F37` | `#3FB950` |
| `--color-focus` | `var(--color-accent)` | same |
| `--color-danger` | `#B42318` | `#F97066` *proposed* |
| `--color-danger-ink` | `#FFFFFF` | `#1A0A08` *proposed* |
| `--color-danger-soft` / `-border` | `#FEE4E2` / `#F1B8B2` | `#3A1714` / `#7A2E27` *proposed* |
| `--color-strip` / `-hole` | `#15161A` / `#F6F4EE` | `#1E2220` / `#0E100F` *proposed* |
| `--color-strip-waiting` / `-text` | `#2A2B31` / `#B4B1A8` | `#2C312E` / `#B4B1A8` *proposed* |
| `--color-dock` / `-active` | `#15161A` / `#2A2B31` | `#212522` / `#2C312E` |
| `--color-dock-ink` / `-muted` / `-accent` | `#FFF` / `#B4B1A8` / `#3FB950` | `#ECEDE8` / `#9A9E97` / `#3FB950` |

| `--color-band` / `--color-band-ink` | `#15161A` / `#FFFFFF` | `#212522` / `#ECEDE8` *proposed* |

`--color-band` (Phase 5c) is the landing page's closing "Have a video in
mind?" band. Light matches the board (near-black). Dark has no board, so it
reuses the raised tint: it reads as a card, not a contrast band. Contrast: band
ink on band 18.08 (L) / 13.20 (D); the green `btn-primary` on the band 3.56 (L,
non-text, needs 3) / 6.11 (D); band against dark paper 1.23 (a surface step,
like the other cards).

### Contrast (WCAG 2.x, computed)

| Pair | Ratio | Need |
|---|---|---|
| L danger on paper / surface / soft | 5.98 / 6.57 / 5.45 | 4.5 |
| White on L danger | 6.57 | 4.5 |
| D danger on paper / surface / soft | 6.85 / 6.29 / 5.74 | 4.5 |
| D danger-ink on D danger | 6.91 | 4.5 |
| D danger-border vs surface (non-text) | 1.88 | decorative only — the text carries the state |
| L accent on paper | 4.62 | 4.5 |
| on-accent on L accent | 5.08 | 4.5 |
| D accent on paper | 7.52 | 4.5 |
| D on-accent on D accent | 6.90 | 4.5 |
| strip-waiting-text on waiting (L / D) | 6.58 / 6.18 | 4.5 |
| D strip vs paper (non-text) | 1.19 | decorative only |
| Dock muted label (L) / on tint (D) | 8.43 / 5.70 | 4.5 |
| Dock accent icon on active pill (L / D) | 5.55 / 5.21 | 3 (graphic) |
| Focus ring (accent) on L dock | 3.56 | 3 (non-text) |
| Muted on paper (L) / on surface (D) | 5.76 / 6.44 | 4.5 |

The two sub-3 rows are fills that never carry information on their own.

**Phase 4 dark-mode audit (2026-11-01) — no token changed.** Every danger/error
pair was recomputed from `tokens.css` and every text pair passes in both
themes, so `tokens.css` is untouched. Added rows:

| Pair (L / D) | Ratio | Need |
|---|---|---|
| ink-2 on danger-soft (run-notice body) | 9.24 / 9.55 | 4.5 |
| danger 2px edge vs danger-soft (failed frame) | 5.45 / 5.74 | 3 (UI) |
| danger-border vs surface / paper (alert hairline, Failed badge) | 1.72 / 1.88 · 1.56 / 2.04 | decorative — fill + danger text carry the state |
| accent-strong on accent-soft ("Saved on this device") | 6.64 / 9.34 | 4.5 |
| muted on surface / tint (key help, release meta, legal meta) | 6.34 / 6.44 · 5.27 / 5.70 | 4.5 |
| input-border vs surface (Remove key edge) | 3.58 / 3.56 | 3 (UI) |
| input-border vs tint (Offline / Lost dashed tile) | 2.98 / 3.15 | decorative — not a control; title + lede carry it |

The danger-border hairline fails 3:1 in both themes by design: WCAG 1.4.11
does not require a contrasting container edge when the component is identified
by its contents, and raising it would make every error box shout. Revisit only
if an error state ever relies on its border alone.

### Temporary aliases — removed in Phase 2

Phase 1 shipped an alias block mapping the Terminal-era names (`paper-2`,
`nav-bg`, `paper-3`, `rule-2`, `accent-ink`, `font-body`, `font-display`) onto
the new tokens. Phase 2 migrated every caller and deleted the block; a grep for
those names across `frontend/app` and `frontend/components` returns nothing.
Use the real token names only.

## Type

- **UI: Hanken Grotesk**, the variable file (one file covers 400–700, smaller than four statics). `--font-ui`.
- **Headlines and reading text: Newsreader, variable (wght + opsz, roman + italic) since Phase 2.** `--font-serif`. Opt-in by class only (`.view-title` (Phase 4: API key, Releases, Privacy, Terms; History's `.history-title` shares it), `.legal-heading`, `.key-guide-title`, `.offline-title`, `.sheet-title`, `.intake-title`, `.run-title`, `.result-title`, `.prose-serif`); base `h1–h3` deliberately do **not** set a family. Phase 1 loaded a single static 400; Phase 2 moved Notes/TL;DR into the serif, and their markdown carries bold headings, `**strong**` and `*emphasis*`, which a static 400 would have faux-bolded and faux-italicised. The opsz axis is what makes the 56px headline match the boards' display cut.
- **Serif reading measure: `--measure-serif: 36rem`**, measured in the browser at 19px: 576px ≈ 74 characters per line in Notes/TL;DR, 69 in transcript lines. 40rem measured 82 and was cut. Phone (18px, 316px column) runs ~43.
- Both via `next/font/google` → self-hosted under `/_next/static/media`; `scripts/build-sw.mjs` now precaches `.woff2` so the offline page and the Capacitor export keep their type.

## Shape and spacing

`--radius-card` 20px, `--radius-control` 12px, plus 16px and pill (999px).
`--page-gutter: clamp(1rem, 4vw, 3rem)`; `--shell-width` is 74rem of content +
two max gutters. Touch targets ≥ 44px; focus is a 2px accent outline at 2px
offset everywhere.

## Shell mode

Two chromes, chosen before first paint by `SHELL_INIT_SCRIPT` in `layout.tsx`,
stamped as `<html data-shell="web"|"app">`:

- **app** when `display-mode: standalone` matches, `navigator.standalone === true` (iOS), or `Capacitor.isNativePlatform()`. If the first check says web, it re-checks once at `DOMContentLoaded` in case the Capacitor bridge was injected late.
- **web** otherwise, and on any failure.
- **Testing override:** `localStorage.videolens_shell = "app"` or `"web"` wins over detection. Not exposed in UI.

Both chromes are always rendered; CSS shows one (`display: none` on the other, so
the hidden one is out of the tab order and the accessibility tree). Layout
details are in `app-shell-layout.md`.

## Where it deliberately differs from the shots

- **More sheet covers the dock.** The shot draws the dock above the sheet. The sheet is a native modal `<dialog>` (top layer, inert page, platform Escape); keeping the dock interactive above it would need a non-modal dialog and a hand-rolled trap. Correct semantics won.
- **Theme toggle glyph shows the destination**: moon in light, sun in dark. MainDark draws a moon.
- **Dark dock is a raised tint** (`#212522`), not an inverted light bar — an inverted bar on a near-black page was the loudest element on screen.
- **App mode on a wide window** (changed in Phase 2, settled 2026-11-01): the bottom tab bar and More sheet are phone-only — `≤ 37.5rem`. A wider installed window gets the web chrome whole: the top bar and the footer, which is its way to Privacy/Terms (owner decision; they are not added to the top-bar menu). CSS only.
- **design/newshots/ supersedes design/shots/** for ProgressCaptions, ProgressUploadMobile, ProgressFailed, ProgressLostWeb and ResultsOnScreenText(Mobile). One new token: `--color-strip-skipped-edge` (dashed edge of a skipped frame, light #5E5F66 / dark #5A615C).
- **Phase 4 boards** (`design/phase4-boards/`; no suffix = desktop 1280, `Web` = phone browser shell, `Mobile` = installed-app shell) cover API key, Releases, Privacy, Terms and Offline. They were rendered with fallback fonts — match size, weight, spacing and hierarchy, never glyph shapes; the real faces are Newsreader and Hanken Grotesk. Truth-driven copy deviations (no "few free runs", no Open History offline, no release bullets, the phone boards' key sentence on desktop, "Effective" over "Last updated") are recorded in `byok-api-key.md`, `release-notes.md`, `legal-offline-routes.md`.
- **Phase 2 deviations** are listed per shot in `mem/20261101-redesign-phase2-core-flow.md` and summarised in `upload-form.md`, `run-status-pipeline.md` and `results-view.md`.

## Overrides of tooling suggestions

ui-ux-pro-max proposed a teal/orange palette with Lora/Raleway. Overridden in
favour of the owner's handoff (hallmark: a supplied design system beats a
generated one). Nothing is persisted outside this doc and `frontend/app/tokens.css`.

## Changelog

- 2026-11-01 · frontend agent · created: Phase 1 of the editorial redesign — tokens, fonts, shell-mode detection, dark danger/strip/dock values with contrast table, deviations from the shots
- 2026-11-01 · frontend agent · Phase 2: status, alias block removed, Newsreader variable + `--measure-serif` (measured), wide installed windows get the top bar, `design-system/` references dropped (that folder no longer exists)
- 2026-11-01 · frontend agent · owner follow-ups: results row is underlined tabs (not a segmented control) with TL;DR default; service notice moved into the editorial system; intake grid tracks floorless. See results-view.md, capability-reporting.md, upload-form.md
- 2026-11-01 · frontend agent · owner answers applied: TL;DR key-takeaway label, bold filmstrip labels; corrected the Privacy/Terms note (they were already in the More sheet; the gap is wide installed windows only)
- 2026-11-01 · frontend agent · final Phase 2 round: design/newshots built (captions route, File received, failed/lost notice, text-only On-screen); wide installed windows show the footer; added --color-strip-skipped-edge
- 2026-11-01 · frontend agent (Phase 3) · History poster grid built on the existing --poster-1..5 and --radius-poster (no new tokens); new classes .history*, .filter-pill, .sort-select, .poster* in globals.css HISTORY block. See run-history.md
- 2026-11-01 · frontend agent (Phase 4) · API key / Releases / Privacy / Terms / Offline built editorially (shared `.view-title`, no new tokens); dark-mode contrast audit of danger and new pairs, computed — all text passes, no token change; no-board pages listed
- 2026-11-01 · frontend agent (Phase 4, boards) · pages rebuilt to design/phase4-boards/; `.view-title` (and History's title) now clamp(2.25rem, 1.75rem + 1.6vw, 3rem) = 36px phone / 48px at 1280 to match the boards; new `.release-latest` pill reuses accent-strong on accent-soft (already audited both themes); no token change
- 2026-11-01 · frontend agent (Phase 5c) · added --color-band / --color-band-ink (landing closing band) with computed contrast
