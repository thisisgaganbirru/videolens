# Editorial design direction (current)

**Status: Phase 1 implemented** (tokens, fonts, app shell, bottom tab bar, More
sheet). Supersedes `design-direction-terminal.md`. Phases 2+ (intake, results,
history, panels re-skinned to these tokens) are not done yet — those views still
render with the Terminal-era component classes, now coloured through the
temporary aliases below.

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
- `design-system/videolens/MASTER.md` (repo root) — the ui-ux-pro-max persisted design system, overwritten with this locked system.

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

### Temporary aliases

`tokens.css` ends with a clearly marked alias block mapping the Terminal-era
names onto the new tokens so untouched views keep rendering:
`paper-2`/`nav-bg` → `surface`, `paper-3` → `tint`, `rule-2` → `border-strong`,
`accent-ink` → `on-accent`, `font-body` → `font-ui`, `font-display` →
`font-serif`. **Delete each alias when its last caller is ported** (Phase 2+).

## Type

- **UI: Hanken Grotesk**, the variable file (one file covers 400–700, smaller than four statics). `--font-ui`.
- **Headlines: Newsreader 400 only.** `--font-serif`. Opt-in via `.page-title` and `.sheet-title`; base `h1–h3` deliberately do **not** set a family, because Newsreader is loaded at one weight and a bold heading would be faux-bolded.
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
- **App mode on a wide window** keeps the bottom bar (centred, max 30rem) rather than switching to the top links — an installed desktop PWA is still "the app". Open question for the owner.

## Overrides of tooling suggestions

ui-ux-pro-max proposed a teal/orange palette with Lora/Raleway. Overridden in
favour of the owner's handoff (hallmark: a supplied design system beats a
generated one). Recorded in `design-system/videolens/MASTER.md`.

## Changelog

- 2026-11-01 · frontend agent · created: Phase 1 of the editorial redesign — tokens, fonts, shell-mode detection, dark danger/strip/dock values with contrast table, deviations from the shots
