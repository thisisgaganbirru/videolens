# Background theme system

The "Theme" tab: 8 selectable full-page animated backgrounds (WebGL/CSS shaders and gradients), one active at a time.

**Files**
- `frontend/components/ui/AppBackground.tsx` — `AppBackground` (the actual `<div>` that renders whichever background is active), plus the shared `BackgroundStyle` type, `ALL_BACKGROUND_STYLES`, and the get/set/random storage helpers.
- `frontend/components/ui/BackgroundSwitcher.tsx` — `BackgroundPickerPanel`, the picker UI shown in the Theme tab (category filter + shuffle + grid of options).
- `frontend/components/ui/backgrounds/*.tsx` — the 8 individual background components: `AuroraFlow`, `LiquidChroma`, `CyberGrid`, `GlassOrbs`, `CosmicNebula`, `CharcoalGlow`, `SynthwaveHorizon`, `DigitalMatrix`.

**Selection persistence (intentional)**: a manually-picked theme holds only for the current tab/session, via `sessionStorage["videolens_manual_bg"]`. A fresh tab or reload with no session value falls back to `getRandomBackgroundStyle()` — that's by design, not a bug: each new visit is meant to surface a different background rather than freeze on whatever was last picked. Cross-component sync uses a custom `window` event (`"videolens-bg-change"`) rather than React context, since `AppBackground` (in the page chrome) and `BackgroundPickerPanel` (in the Theme tab) aren't in a shared component tree.

**Vestigial code, not a bug**: `setStoredBackgroundStyle()` also writes to `localStorage["videolens_bg_style"]`, but `getStoredBackgroundStyle()` never reads it — only `sessionStorage` is consulted. Since session-only persistence is the intended behavior, this `localStorage` write is simply dead (harmless, but removable if someone's cleaning up this file).

**Tests**: none (see `run-analysis-hook.md`).
