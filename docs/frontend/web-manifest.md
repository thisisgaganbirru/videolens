# Web app manifest

`frontend/app/manifest.ts` generates `/manifest.webmanifest` for PWA install
metadata and Web Share Target support. The share target uses a GET action and
explicitly declares `application/x-www-form-urlencoded`, the valid encoding
for GET share targets. This avoids browser manifest validation warnings.

`background_color` and `theme_color` are both the editorial paper `#F6F4EE`
(was the Terminal palette), matching `THEME_COLOR.light` in
`components/theme.ts` and Capacitor's `android.backgroundColor`, so the splash,
install sheet and first frame are one colour. `start_url`, `id` and
`share_target` were deliberately not touched (Phase 5 owns them).

## Changelog

- 2026-11-01 · frontend agent · background_color/theme_color → #F6F4EE for the editorial redesign
