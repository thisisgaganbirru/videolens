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

**Caption-only analysis**: `analyze_captions(captions, api_key)` is a second, separate entry point used when the media could not be downloaded at all (see `docs/backend/run-processing.md`). It is text-only — no file upload, no `_wait_until_active` polling, no retry wrapper — and runs under its own `CAPTION_SYSTEM_INSTRUCTION` rather than the normal one.

A separate instruction is the whole point. The main prompt asks for on-screen text and visual context; asking for those when the model has only words is an invitation to invent them. The caption instruction therefore *forbids* describing visuals, requires `screen_text`/`screen_text_segments` to stay empty, warns that auto-captions contain mishearings, and requires the summary to state that the analysis came from captions alone. Verified live: a real caption-only run returned `screen_text: ''` and a summary opening "Based on the caption track alone".

The `<source_metadata>` block is attached here too, on the same terms.

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

**Transient failures**: `_as_domain_error` maps 429 and 5xx onto `AnalysisUnavailableError` — the request was well-formed and the media was fine, so the honest advice is to wait rather than re-pick a file. `analyze_captions` routes through the same mapping, and `ProcessRunUseCase` re-raises it out of the caption fallback rather than reporting the download error, since "Gemini is busy" is truer than "this link couldn't be downloaded".

**Tests**: `backend/tests/infrastructure/ai/test_source_context.py` covers the block builder — field selection, truncation, date formatting, engagement counts, line flattening, fence-forgery stripping, and that the source URL never appears. `GeminiEngine` itself is still not unit tested (would require mocking the `google.genai` client), which is why the prompt-building logic was pulled out into a module that can be.

## Changelog

- 2026-08-20 · main session · sharpened the summary/markdown prompt bullets so the two fields are distinct reads (short prose abstract vs complete structured notes) instead of the same content in two formats
- 2026-08-21 · main session · classified 429/5xx as AnalysisUnavailableError, and moved the GEMINI_API_KEY hint out of the user-facing message into log_detail
- 2026-08-29 · main session · added `source_context.py` and fed publisher metadata into the prompt as explicitly-untrusted context
- 2026-08-29 · main session · added `analyze_captions` and `CAPTION_SYSTEM_INSTRUCTION` for the caption-only salvage path
- 2026-08-29 · main session · merged dev: routed `analyze_captions` through `_as_domain_error` so a busy-Gemini caption run says so instead of blaming the link
