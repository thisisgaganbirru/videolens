# Free runs (frontend)

Anonymous devices get a few free runs per UTC day. Without a saved Gemini key,
the intake shows how many are left, and once they are spent it blocks
submitting until a key is saved. With a key saved there is no banner and no
limit. The server half (signing, counters, the IP backstop, how easy it is to
bypass) is `docs/backend/free-runs.md`.

**Files**
- `frontend/domain/entities.ts`: `FreeRunsStatus`.
- `frontend/domain/errors.ts`: `ApiError` now carries `code`, `limit` and `used` from the error body, so callers branch on `code` and never on message text.
- `frontend/domain/ports.ts`: `FreeRunsGateway`, `DeviceTokenStore`, and `ApiKeyStore.subscribe`.
- `frontend/infrastructure/freeRunsGateway.ts`: `FetchFreeRunsGateway` (`GET /api/free-runs`). Normalises the body, and writes back any token that differs from the stored one.
- `frontend/infrastructure/deviceTokenStore.ts`: `LocalStorageDeviceTokenStore`, key `videolens-device-token`. Every access is wrapped in try/catch.
- `frontend/infrastructure/clientId.ts`: `getClientId()`, moved out of `runsGateway.ts` now that two adapters send `X-Client-ID`.
- `frontend/infrastructure/runsGateway.ts`: `createRun` sends `X-Device-Token`, and passes the body's `code`/`limit`/`used` into the `ApiError`.
- `frontend/infrastructure/apiKeyStore.ts`: `subscribe()` covers same-tab writes and other tabs' `storage` events.
- `frontend/application/useFreeRuns.ts`: a module-level store plus `useFreeRuns()`, `refreshFreeRuns()`, `markFreeRunsUsed()` and `noteRunAccepted()`.
- `frontend/application/useAnalysisRun.ts`: the 401 retry and the 402 handling in `submit`.
- `frontend/components/FreeRunsBanner.tsx`: the banner.
- `frontend/components/HomeScreen.tsx`: the always-present `.free-runs-slot` (`role="status"`) above the eyebrow, and `blocked` passed to `UploadForm`.
- `frontend/components/UploadForm.tsx`: the `blocked` prop.
- `frontend/app/globals.css`: `.free-runs*`, plus a short-desktop tightening.
- `frontend/components/panels/ApiKeyPanel.tsx`: the lede.
- `frontend/app/privacy/page.tsx`: one sentence about the device token.

## Contract used

- `GET /api/free-runs` (sends `X-Device-Token` when stored, plus `X-Client-ID`) returns `{device_token, limit, used, remaining, resets_at, enabled}`.
- `POST /api/runs` sends `X-Device-Token` alongside `X-Gemini-Api-Key`, and both go on run creation only.
  - 401 `code: "device_token_invalid"`: `refreshFreeRuns()` (which stores the new token), then the same `createRun` again, **once**. A second refusal is shown like any other error.
  - 402 `code: "free_runs_used"`: `markFreeRunsUsed(limit, used)` puts up the limit state straight away, even if the cached count still said runs were left, then confirms with a fresh read. No intake error line, because the banner says it. If the 402 came from "Try again" on the failed view, the screen returns to idle so the banner is visible. With a key saved, the banner is hidden, so the server's sentence is shown instead (unreachable in practice).

## When the status is read

- On mount of the shell (`HomeScreen`, which a tab switch never unmounts), if no key is saved.
- When the saved key is removed (`ApiKeyStore.subscribe`).
- After every accepted run made without a key (`noteRunAccepted`).
- On a 402, and on a 401 (to replace the token).
- When the allowance is spent, once just after `resets_at` (capped at 24h), so a tab left open overnight unblocks itself.

Concurrent reads share one request.

## Staying quiet

The banner shows only when there is no key, the read succeeded, and `enabled`
is true. A failed or offline read clears it rather than leaving a stale count
up. The one exception: after a 402, a failed confirm read keeps the limit state
up (`refusedSinceLastRead`), because the refusal is hard evidence. A saved key
hides the banner in the same render, through `useSyncExternalStore` over
`apiKeyStore`. The server snapshot is "no key", so prerendered HTML and
hydration agree.

## UI (IntakeFreeApp.png, IntakeLimitApp.png, IntakeWeb.png)

- One white strip above the "New analysis" eyebrow on **every** shell (installed app, phone web, desktop web; in the left column on desktop). The sentence is on the left and the near-black `btn btn-ink btn-pill` "Add key" is on the right.
- Copy: "**3 free runs left.** Add your own key for more." The singular is "**1 free run left.**". When spent: "**You have used your free runs.**" with "Add your own key to keep going." on its own line, and the strip gets a `--color-danger-border` hairline. Nothing else turns red.
- "Add key" is a real link to `/app?view=api-key` (was `/?view=api-key` before Phase 5c moved the tool) (plain click goes through `goToMainTab`; middle-click opens a new tab).
- Blocked: Analyze link uses the existing `.btn-primary:disabled` grey. **Browse files is disabled too, and drop is refused** (`dropEffect = "none"`, no highlight). The board draws Browse looking normal, but a control that cannot succeed should not look pressable. The link field and the terms box stay usable, so a typed link survives saving a key and coming back.
- Accessibility: the `.free-runs-slot` wrapper is always rendered with `role="status"` (implicitly polite), so the count and the switch to "used" are announced without moving focus. It is `display: none` while empty.
- Short desktop windows (`min-width: 60rem` and `max-height: 50rem`): while the banner is shown (`.intake-layout:has(.free-runs)`), the top padding drops to 1rem, the headline margin to 1rem, the banner's block padding to 0.5rem and its line-height to 1.35. Measured: 1366×768 fits with no scroll in all six states (3 left, spent, none × light/dark).

## Known issues

- At 1536×674 the intake already scrolls without the banner (587 vs 540 px content band; `upload-form.md`'s 2026-11-01 "no overflow at 1536×674" no longer holds). The banner adds about 46px there. Not addressed here.
- No frontend test runner. Verified with Playwright against mocked `/api/*` (see the mem entry).

## Unreachable server on launch (refinement 4, LCH-06)

A failed read still hides the pill, but it is no longer the only thing that
knew. `refreshFreeRuns` reports each result to
`application/serverReachability.ts` (`noteReadResult`), which flags
"unreachable" on a `NetworkError` only. `HomeScreen` shows a calm
`ReachabilityNotice` in the capability slot ("Can't reach the server right
now. You can still open past runs in History.", or "You're offline right now.
..." when `navigator.onLine` is false). `useFreeRuns` registers with
`onReconnectChance`: while the notice is up, `online`, window `focus` and
`visibilitychange` to visible re-read the allowance if it is still unknown, so
the pill appears on its own. Nothing is blocked. See
`capability-reporting.md` for the other half.

## Changelog

- 2026-11-01 · frontend agent (Phase 5b) · created: device token store, free-runs gateway/port, `useFreeRuns` store, 401 retry-once and 402 limit state in `useAnalysisRun`, `FreeRunsBanner` on all shells, `UploadForm` `blocked`, API key lede and Privacy sentence
- 2026-11-01 · frontend agent (Phase 5c) · Add key now links to /app?view=api-key (via mainTabHref)
- 2026-11-02 · frontend agent (refinement 4) · free-runs read reports reachability; re-read on online/focus/visible while the unreachable notice is up (LCH-06)
