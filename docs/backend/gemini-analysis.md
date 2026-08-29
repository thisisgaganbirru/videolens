# Gemini analysis integration

Uploads the normalized media file to Gemini, waits for it to finish processing, and requests a structured analysis (transcript, on-screen text, summary, markdown notes) matching the `VideoAnalysis` schema directly.

**Files**
- `backend/app/infrastructure/ai/gemini_engine.py` — `GeminiEngine`, implements the `AnalysisEngine` port.
- `backend/app/infrastructure/ai/source_context.py` — `build_source_context`, renders a run's `SourceMetadata` into the prompt block described below. Deliberately SDK-free so it can be tested without a Gemini client.
- `backend/app/domain/entities.py` — `VideoAnalysis`/`TranscriptSegment`/`ScreenTextSegment`, passed directly as `response_schema` to Gemini's structured-output config (no separate parsing/mapping layer — Gemini is asked to return exactly this shape).

**Flow**: `analyze_with_retry` wraps `_analyze` with up to 2 attempts (2s sleep between). `_analyze` uploads the file (`client.aio.files.upload`), polls `_wait_until_active` every 2s up to a 120s timeout for Gemini to finish processing the upload, then calls `generate_content` with the fixed `SYSTEM_INSTRUCTION` prompt, the media part, an optional source-metadata block, and the `VideoAnalysis` response schema. Always deletes the uploaded Gemini file in a `finally` block (best-effort — failure is swallowed).

**Publisher metadata in the prompt**: `analyze_with_retry` takes an optional `SourceMetadata` (URL runs only — uploads pass `None`). `build_source_context` renders it into a `<source_metadata>` block appended *after* the media part, so the model reads the thing it is analyzing before anything the publisher said about it. This exists because the description, title, and upload date carry names, jargon, and dates the pixels do not — the model was previously inventing a title the uploader had already written.

The block is treated as hostile input throughout, because it is arbitrary text from the open internet:
- The preamble labels it `UNVERIFIED`, tells the model never to follow instructions found inside it, and says to trust the media when the two disagree. `SYSTEM_INSTRUCTION` carries the matching half of that rule.
- `OPEN_TAG`/`CLOSE_TAG` occurrences are stripped from every field, so publisher text cannot forge or close the fence.
- Every field except the description is flattened to a single line, so it cannot forge extra `key: value` rows.
- Fields are truncated (title 300, uploader 200, description 2000 chars).
- The `source_url` is **never** sent: `platform` already identifies the site, and the raw URL would only add attacker-controlled query strings.
- Metadata carrying nothing but `platform` yields `None` — no block, no wasted tokens, no added surface.

A useful side effect: because the model is told to flag disagreement, the summary can note where the video differs from what the publisher claimed.

**BYOK vs shared client**: a caller-supplied API key gets its own `genai.Client`, constructed fresh every call and never cached. The shared server key's client (`self._client`) is a single instance cached for the adapter's lifetime (adapter itself is a container-level singleton, so effectively one client per process). This separation is deliberate — the shared-key cache must never accidentally end up holding someone else's credential.

**Configuration error**: if no BYOK key is given and `GEMINI_API_KEY` isn't set, raises `GeminiConfigurationError` — caught by `ProcessRunUseCase` and stored as the run's error message verbatim (it's already a caller-safe message).

**Known issue**: none identified specific to this adapter — retry/timeout/cleanup behavior all looks intentional.

**Tests**: `backend/tests/infrastructure/ai/test_source_context.py` covers the block builder — field selection, truncation, date formatting, engagement counts, line flattening, fence-forgery stripping, and that the source URL never appears. `GeminiEngine` itself is still not unit tested (would require mocking the `google.genai` client), which is why the prompt-building logic was pulled out into a module that can be.

## Changelog
- 2026-08-29 · main session · added `source_context.py` and fed publisher metadata into the prompt as explicitly-untrusted context
