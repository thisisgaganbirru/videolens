# BYOK API key management

Lets someone paste their own Gemini API key so their runs spend their own quota instead of the shared one. See `backend/docs/byok.md` for the server-side half.

**Files**
- `frontend/application/useGeminiApiKey.ts` — `value`/`saved` state, `update`/`save`/`clear` actions.
- `frontend/infrastructure/apiKeyStore.ts` — `LocalStorageApiKeyStore`, implements the `ApiKeyStore` port.
- `frontend/components/panels/ApiKeyPanel.tsx` — the UI (password-style input + Save/Clear).
- `frontend/infrastructure/runsGateway.ts` — reads the stored key on every request to set the `X-Gemini-Api-Key` header.

**Storage**: `localStorage` only, key `videolens-gemini-api-key`. Never sent anywhere except as that one header on run creation — no server-side persistence of the raw key beyond the transient single-use Redis entry described in `backend/docs/byok.md`.

**Known issue**: none — this is intentionally minimal (no key format validation client-side; an invalid key just surfaces as a Gemini error on the resulting run).

**Tests**: none (see `run-analysis-hook.md`).
