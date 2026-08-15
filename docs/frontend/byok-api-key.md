# BYOK API key management

Lets someone paste their own Gemini API key so their runs spend their own quota instead of the shared one. See `backend/docs/byok.md` for the server-side half.

**Files**
- `frontend/application/useGeminiApiKey.ts` — `value`/`saved` state, `update`/`save`/`clear` actions.
- `frontend/infrastructure/apiKeyStore.ts` — `LocalStorageApiKeyStore`, implements the `ApiKeyStore` port.
- `frontend/components/panels/ApiKeyPanel.tsx` — the UI (password-style input + Save/Clear).
- `frontend/infrastructure/runsGateway.ts` — reads the stored key on every request to set the `X-Gemini-Api-Key` header.

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

**Known issue**: none — this is intentionally minimal (no key format validation client-side; an invalid key just surfaces as a Gemini error on the resulting run).

**Tests**: none (see `run-analysis-hook.md`).

## Changelog

- 2026-08-15 · frontend agent · ported ApiKeyPanel; promoted the sr-only label to a visible .card-label, kept the programmatic association
- 2026-08-15 · frontend agent · restructured ApiKeyPanel to place Optional on top label line, started body paragraph on next line, and fixed input field height to 2.5rem single-line bar
