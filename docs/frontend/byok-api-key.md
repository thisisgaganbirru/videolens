# BYOK API key management

Lets someone paste their own Gemini API key so their runs spend their own quota instead of the shared one. See `backend/docs/byok.md` for the server-side half.

**Files**
- `frontend/application/useGeminiApiKey.ts` — `value`/`saved` state, `update`/`save`/`clear` actions.
- `frontend/infrastructure/apiKeyStore.ts` — `LocalStorageApiKeyStore`, implements the `ApiKeyStore` port.
- `frontend/components/panels/ApiKeyPanel.tsx` — the UI (password-style input + Save/Clear).
- `frontend/infrastructure/runsGateway.ts` — reads the stored key on every request to set the `X-Gemini-Api-Key` header.
- `frontend/components/CapabilityNotice.tsx` — `CapabilityCallout`, the `daily_budget` notice this panel renders. See `capability-reporting.md`.

**Storage**: `localStorage` only, key `videolens-gemini-api-key`. Never sent anywhere except as that one header on run creation — no server-side persistence of the raw key beyond the transient single-use Redis entry described in `backend/docs/byok.md`.

**Label is visible, not `sr-only`.** An earlier accessibility audit added an
`sr-only` `<label htmlFor="gemini-api-key">` because the field was identified
only by a placeholder. The Terminal redesign promoted it to a visible
`.card-label`, matching the mockup — strictly stronger, since the field is no
longer placeholder-identified for sighted users either. The programmatic
`htmlFor`/`id` association is unchanged; keep it through any restyle.

The BYOK explanatory copy names `localStorage` and the `X-Gemini-Api-Key`
header explicitly. That's a deliberate user-trust statement — don't trim it for
visual tidiness.

**The `daily_budget` capability notice.** The panel takes an optional
`budgetCapability` prop — the deployment's `daily_budget` row, handed down by
`HomeScreen`. When it is `unavailable` (the shared budget is spent for the UTC
day) a line renders directly under the `Optional` label, above the explanatory
prose:

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

## Changelog

- 2026-08-15 · frontend agent · ported ApiKeyPanel; promoted the sr-only label to a visible .card-label, kept the programmatic association
- 2026-08-15 · frontend agent · restructured ApiKeyPanel to place Optional on top label line, started body paragraph on next line, and fixed input field height to 2.5rem single-line bar
- 2026-08-29 · frontend agent · added the optional `budgetCapability` prop and the `daily_budget` callout under the Optional label (backend sentence verbatim, no lead) — see `capability-reporting.md`
