# Gemini analysis integration

Uploads the normalized media file to Gemini, waits for it to finish processing, and requests a structured analysis (transcript, on-screen text, summary, markdown notes) matching the `VideoAnalysis` schema directly.

**Files**
- `backend/app/infrastructure/ai/gemini_engine.py` — `GeminiEngine`, implements the `AnalysisEngine` port.
- `backend/app/domain/entities.py` — `VideoAnalysis`/`TranscriptSegment`/`ScreenTextSegment`, passed directly as `response_schema` to Gemini's structured-output config (no separate parsing/mapping layer — Gemini is asked to return exactly this shape).

**Flow**: `analyze_with_retry` wraps `_analyze` with up to 2 attempts (2s sleep between). `_analyze` uploads the file (`client.aio.files.upload`), polls `_wait_until_active` every 2s up to a 120s timeout for Gemini to finish processing the upload, then calls `generate_content` with the fixed `SYSTEM_INSTRUCTION` prompt and the `VideoAnalysis` response schema. Always deletes the uploaded Gemini file in a `finally` block (best-effort — failure is swallowed).

**BYOK vs shared client**: a caller-supplied API key gets its own `genai.Client`, constructed fresh every call and never cached. The shared server key's client (`self._client`) is a single instance cached for the adapter's lifetime (adapter itself is a container-level singleton, so effectively one client per process). This separation is deliberate — the shared-key cache must never accidentally end up holding someone else's credential.

**Configuration error**: if no BYOK key is given and `GEMINI_API_KEY` isn't set, raises `GeminiConfigurationError` — caught by `ProcessRunUseCase` and stored as the run's error message verbatim (it's already a caller-safe message).

**Known issue**: none identified specific to this adapter — retry/timeout/cleanup behavior all looks intentional.

**Tests**: none currently — this adapter isn't unit tested (would require mocking the `google.genai` client).
