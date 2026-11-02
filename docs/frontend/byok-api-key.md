# BYOK API key management

Lets someone paste their own Gemini API key so their runs spend their own quota instead of the shared one. See `backend/docs/byok.md` for the server-side half.

**Files**
- `frontend/application/useGeminiApiKey.ts` — one state object `{ value, stored, saved }` (`stored`: a key is in the store; `saved`: the field matches it), `update`/`save`/`clear` actions. `save()` re-reads the store so the field shows the trimmed value.
- `frontend/infrastructure/apiKeyStore.ts` — `LocalStorageApiKeyStore`, implements the `ApiKeyStore` port.
- `frontend/components/panels/ApiKeyPanel.tsx` — the UI (Phase 4 editorial page, below).
- `frontend/infrastructure/runsGateway.ts` — reads the stored key **only in `createRun`** to set the `X-Gemini-Api-Key` header (see below).
- `frontend/components/CapabilityNotice.tsx` — `CapabilityCallout`, the `daily_budget` notice this panel renders. See `capability-reporting.md`.

**Storage**: `localStorage` only, key `videolens-gemini-api-key`. Never sent anywhere except as that one header on run creation (`POST /api/runs`) — no server-side persistence of the raw key beyond the transient single-use Redis entry described in `backend/docs/byok.md`.

## The header goes on run creation only (Phase 4, 2026-11-01)

Until Phase 4 `FetchRunsGateway.requestHeaders()` attached `X-Gemini-Api-Key`
to **every** request — run polling, history, releases, capabilities — so the
key crossed the wire dozens of times per run although the backend reads it in
exactly one handler (`create_run` in `backend/app/interface/api/routes.py`; the
rate limiter and every other route ignore it). That contradicted the panel's
own copy. Now `requestHeaders({ withGeminiKey })` adds it only when asked and
`send(path, init, { withGeminiKey })` defaults to `false`; only `createRun`
passes `true`. `X-Client-ID` still goes on every request (it scopes history).
Verified with Playwright request interception: `POST /api/runs` carries the
key; `GET /api/runs/{id}` and `GET /api/runs` carry none; all three carry
`X-Client-ID`. If a future endpoint genuinely needs the key, opt it in
explicitly — never flip the default.

## Layout (Phase 4, `design/phase4-boards/ApiKey*.png`)

Centred `.key-page` column (43.5rem, the board's 696px): serif `.view-title`
"API key", lede, the `daily_budget` callout when present, then a white
`.key-card` form — visible label, 3rem password field with an eye toggle
(`aria-pressed`, "Show key"/"Hide key"), help line, **Save key** (primary pill)
and **Remove key** (grey `--color-input-border` edge, shown only while a key is
stored), and a `role="status"` slot: "Saved on this device" (accent-soft pill),
"Removed from this device", or "Not saved yet". Saving an empty field shows
`.error-note` "Paste your key first, then save it." and focuses the field;
saving re-masks the field. Below, a tint "Where to get a key" panel with three
numbered steps and a link to Google AI Studio (new tab, sr-only note, no
icon — the boards draw none). Desktop, phone web and phone app each have a
board (`ApiKey.png`, `ApiKeyWeb.png`, `ApiKeyMobile.png`); on phones the status
pill wraps under the buttons as drawn.

**Copy deviations from the boards (truth over fidelity).** Since Phase 5b the
lede is the boards' verbatim, "Optional. You get a few free runs. Add your own
Gemini key to keep going. It is stored in this browser only.", because the
per-device free-run allowance now exists (`free-runs.md`). The help line is
the *phone* boards' sentence on every size — "Your key is stored in this
browser. It is sent with your own runs and held briefly on the server while a
run is processed." — because the desktop board's "We never store it on a
server" is not quite true: in distributed mode the key waits in a single-use
Redis entry until the worker reads it (see BYOK in the root CLAUDE.md).

**Label is visible, not `sr-only`.** An earlier accessibility audit added an
`sr-only` `<label htmlFor="gemini-api-key">` because the field was identified
only by a placeholder. The Terminal redesign promoted it to a visible
`.card-label`, matching the mockup — strictly stronger, since the field is no
longer placeholder-identified for sighted users either. The programmatic
`htmlFor`/`id` association is unchanged; keep it through any restyle.

The BYOK explanatory copy says where the key lives ("stored in this
browser") and when it travels ("sent with your own runs" — it rides only on
`POST /api/runs`, never polls or history) — both literally true. The header
name is no longer printed; the boards drop it. That's a deliberate user-trust statement — don't trim it for
visual tidiness.

**The `daily_budget` capability notice.** The panel takes an optional
`budgetCapability` prop — the deployment's `daily_budget` row, handed down by
`HomeScreen`. When it is `unavailable` (the shared budget is spent for the UTC
day) a line renders directly under the lede, above the form:

> Today's shared run budget is exhausted. Bring-your-own-key runs are unaffected.

That is the backend's `detail` **verbatim, with no frontend lead** — unlike the
URL-field notice, this sentence already says both halves on its own, and the
rule this codebase follows for server-written sentences is to show them rather
than paraphrase them.

This is the one screen where that row changes what the user should do: an
exhausted shared budget does not stop a BYOK run, so the panel holding the key
field *is* the answer to it. It sits above the prose rather than below because
in that state it is the reason to act, and the prose is the explanation of how.
The `Optional` label is deliberately left alone — relabelling it off backend
state is a bigger claim than one notice line.

**Known issue**: none — this is intentionally minimal (no key format validation client-side; an invalid key just surfaces as a Gemini error on the resulting run).

**Tests**: none (see `run-analysis-hook.md`).

## Refinement 6 (2026-11-02)

**A11-07.** The "Get a key from Google AI Studio" link (`.key-guide-link`) is
`--color-accent-strong` (hover `--color-ink`) instead of `--color-accent`:
6.14:1 on the guide's tint in light, 10.1:1 in dark (was under 4.5:1 in
light). Existing tokens only.

## Changelog

- 2026-08-15 · frontend agent · ported ApiKeyPanel; promoted the sr-only label to a visible .card-label, kept the programmatic association
- 2026-08-15 · frontend agent · restructured ApiKeyPanel to place Optional on top label line, started body paragraph on next line, and fixed input field height to 2.5rem single-line bar
- 2026-08-29 · frontend agent · added the optional `budgetCapability` prop and the `daily_budget` callout under the Optional label (backend sentence verbatim, no lead) — see `capability-reporting.md`
- 2026-11-01 · frontend agent (Phase 4) · `X-Gemini-Api-Key` now sent only on `createRun` (was every request); rebuilt the panel as the editorial ApiKey page (reveal toggle, empty-save error, status slot, Remove key, Where-to-get-a-key panel); hook state unified
- 2026-11-01 · frontend agent (Phase 4, boards) · rebuilt to design/phase4-boards/ApiKey*.png: lede and help copy per boards except two truth deviations (no "few free runs"; phone boards' "held briefly on the server" sentence on every size instead of desktop's "never store it on a server"), header name no longer printed, ExternalLink icon dropped from the AI Studio link, `.key-header` wrapper removed
- 2026-11-01 · frontend agent (Phase 5b) · lede now the boards' "You get a few free runs" sentence; `ApiKeyStore` gained `subscribe()` so saving or removing a key updates the free-run banner at once; `X-Device-Token` now rides on `createRun` beside the key (see `free-runs.md`)
- 2026-11-02 · frontend agent (refinement 6) · A11-07 AI Studio link uses --color-accent-strong (6.14:1 light, 10.1:1 dark)
