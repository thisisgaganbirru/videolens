# Gemini analysis integration

Uploads the normalized media file to Gemini, waits for it to finish processing, and requests a structured analysis (transcript, on-screen text, summary, markdown notes) matching the `VideoAnalysis` schema directly.

**Files**
- `backend/app/infrastructure/ai/gemini_engine.py` — `GeminiEngine`, implements the `AnalysisEngine` port.
- `backend/app/domain/entities.py` — `VideoAnalysis`/`TranscriptSegment`/`ScreenTextSegment`, passed directly as `response_schema` to Gemini's structured-output config (no separate parsing/mapping layer — Gemini is asked to return exactly this shape).

**Flow**: `analyze_with_retry` wraps `_analyze` with up to 2 attempts (2s sleep between). `_analyze` uploads the file (`client.aio.files.upload`), polls `_wait_until_active` every 2s up to a 120s timeout for Gemini to finish processing the upload, then calls `generate_content` with the fixed `SYSTEM_INSTRUCTION` prompt and the `VideoAnalysis` response schema. Always deletes the uploaded Gemini file in a `finally` block (best-effort — failure is swallowed).

**BYOK vs shared client**: a caller-supplied API key gets its own `genai.Client`, constructed fresh every call and never cached. The shared server key's client (`self._client`) is a single instance cached for the adapter's lifetime (adapter itself is a container-level singleton, so effectively one client per process). This separation is deliberate — the shared-key cache must never accidentally end up holding someone else's credential.

**Configuration error**: if no BYOK key is given and `GEMINI_API_KEY` isn't set, raises `GeminiConfigurationError` — caught by `ProcessRunUseCase` and stored as the run's error message verbatim (it's already a caller-safe message).

**`summary` vs `markdown`**: these are two different reads of the same video, not
one field in two formats, and the only thing enforcing that is the prompt —
`VideoAnalysis` declares both as bare `str` with no `Field(description=...)`, so
Gemini sees nothing but the field name from the schema itself. `summary` is a
2-4 sentence plain-prose abstract with no markdown at all, answering whether the
video is worth watching; `markdown` is structured notes with headings and bullets,
complete enough to replace watching it. The prompt says explicitly that they are
read side by side and must not be two versions of the same paragraph.

Before 2026-08-20 the two bullets read only "a natural language summary of what
the video covers" and "well-formatted markdown notes combining speech and visual
context" — nothing about length, depth, or audience — so on a short clip the two
fields collapsed into near-duplicates. If you edit this prompt, keep the contrast
between the two explicit; the UI shows them as adjacent tabs (TL;DR and Notes),
which makes any overlap immediately visible.

**Transient failures**: `_as_domain_error` maps 429/500/502/503/504 onto
`AnalysisUnavailableError` so a busy model is not reported as an unknown
failure — see `../error-messaging.md`. The retry loop around it is still 2
attempts with a flat 2s sleep, which is too short to outlast the demand spike
Google's own 503 describes; that is tracked as a known issue there.

**Known issue**: none identified specific to this adapter — retry/timeout/cleanup behavior all looks intentional.

**Tests**: none currently — this adapter isn't unit tested (would require mocking the `google.genai` client).

## Changelog

- 2026-08-20 · main session · sharpened the summary/markdown prompt bullets so the two fields are distinct reads (short prose abstract vs complete structured notes) instead of the same content in two formats
- 2026-08-21 · main session · classified 429/5xx as AnalysisUnavailableError, and moved the GEMINI_API_KEY hint out of the user-facing message into log_detail
