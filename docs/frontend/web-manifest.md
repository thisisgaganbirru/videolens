# Web app manifest

`frontend/app/manifest.ts` generates `/manifest.webmanifest` for PWA install
metadata and Web Share Target support. The share target uses a GET action and
explicitly declares `application/x-www-form-urlencoded`, the valid encoding
for GET share targets. This avoids browser manifest validation warnings.

`background_color` and `theme_color` are both the editorial paper `#F6F4EE`
(was the Terminal palette), matching `THEME_COLOR.light` in
`components/theme.ts` and Capacitor's `android.backgroundColor`, so the splash,
install sheet and first frame are one colour. `start_url`, `id` and
`share_target` were deliberately not touched until Phase 5c (below).

## Phase 5c: `id`, `start_url`, `scope` (2026-11-01)

The tool moved to `/app` and `/` became a landing page (`landing-page.md`).

| Field | Value | Why |
|---|---|---|
| `id` | `"/"` | There was no `id` before, so browsers used `start_url` (`"/"`) as the app's identity. Pinning `id` to that same value means existing installs keep their identity and pick up the new `start_url` as an update, instead of the browser treating the manifest as a different app. It must never change again. |
| `start_url` | `"/app"` | The installed app opens the tool, not the landing |
| `scope` | `"/"` | The landing, `/privacy`, `/terms` and `/offline` stay inside the installed window |
| `shortcuts` | Analyze `/app`, History `/app?view=history` | |
| `share_target.action` | `/app?share-target=1` | Same GET params as before |

Older installs whose cached manifest still points at `/` or `/?share-target=1` keep working: the landing's pre-paint script sends those to `/app` with the query (`landing-page.md`). An installed launch of `/` also goes to `/app`.

Not verified: how long a given browser takes to pick up the new `start_url` on an existing install. Chrome re-checks the manifest periodically; until it does, the install opens `/`, which redirects.

## Changelog

- 2026-11-01 · frontend agent · background_color/theme_color → #F6F4EE for the editorial redesign
- 2026-11-01 · frontend agent (Phase 5c) · id pinned to "/", start_url "/app", scope "/", shortcuts and share_target.action moved to /app
- 2026-11-12 · launch-checklist session · `icon-192.png`, `icon-512.png`, `apple-touch-icon.png` quantised to 255 colours (PSNR ≈ 50 dB; 31→10 KB, 199→65 KB, 27→9 KB), `icon-1024.png` stripped losslessly; `public/favicon.ico` added and listed first in `metadata.icons`
