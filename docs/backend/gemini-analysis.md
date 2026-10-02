# Gemini analysis integration

Uploads the normalized media file to Gemini, waits for it to finish processing, and requests a structured analysis (transcript, on-screen text, summary, markdown notes) matching the `VideoAnalysis` schema directly.

**Files**
- `backend/app/infrastructure/ai/gemini_engine.py` — `GeminiEngine`, implements the `AnalysisEngine` port.
- `backend/app/infrastructure/ai/source_context.py` — `build_source_context`, renders a run's `SourceMetadata` into the prompt block described below. Deliberately SDK-free so it can be tested without a Gemini client.
- `backend/app/domain/entities.py` — `VideoAnalysis`/`TranscriptSegment`/`ScreenTextSegment`, passed directly as `response_schema` to Gemini's structured-output config (no separate parsing/mapping layer — Gemini is asked to return exactly this shape).

**Flow**: `_analyze` uploads the file **once** (`client.aio.files.upload`, itself wrapped in the transient-only backoff below), polls `_wait_until_active` every 2s up to a 120s timeout for Gemini to finish processing the upload, then calls `generate_content` through `_generate_with_retry` with the fixed `SYSTEM_INSTRUCTION` prompt, the media part, an optional source-metadata block, and the `VideoAnalysis` response schema. Only the failing call is retried — a 503 from `generate_content` never re-uploads the file. Always deletes the uploaded Gemini file in a `finally` block (best-effort — failure is swallowed). `analyze_with_retry` (the port method) wraps `_analyze`; see "Transient failures" for what its outer loop still does.

**Media resolution and token usage (paid tier)**: `analyze_with_retry` also takes `resolution: MediaResolution` and `on_usage: UsageCallback`, both forwarded to `_analyze`. `ProcessRunUseCase` picks the resolution with `domain.entitlements.media_resolution_for(duration)` (media over 15 minutes → `LOW`); `_media_resolution` maps `LOW` to `types.MediaResolution.MEDIA_RESOLUTION_LOW` and leaves the SDK default otherwise (or when the SDK lacks the enum). It is set on the single `GenerateContentConfig` handed to `_generate_with_retry`, so a run that falls back to `GEMINI_FALLBACK_MODEL` is analyzed at the same resolution. `_usage_from(response)` reads `usage_metadata` (`prompt_token_count`/`candidates_token_count`) into a `TokenUsage`, or `None` when Gemini reported nothing; `on_usage` is awaited **once**, from the response that succeeded — whichever model served it — and never for failed attempts. `analyze_captions` takes neither (no media, and caption runs are not token-metered here).

**Publisher metadata in the prompt**: `analyze_with_retry` takes an optional `SourceMetadata` (URL runs only — uploads pass `None`). `build_source_context` renders it into a `<source_metadata>` block appended *after* the media part, so the model reads the thing it is analyzing before anything the publisher said about it. This exists because the description, title, and upload date carry names, jargon, and dates the pixels do not — the model was previously inventing a title the uploader had already written.

The block is treated as hostile input throughout, because it is arbitrary text from the open internet:
- The preamble labels it `UNVERIFIED`, tells the model never to follow instructions found inside it, and says to trust the media when the two disagree. `SYSTEM_INSTRUCTION` carries the matching half of that rule.
- `OPEN_TAG`/`CLOSE_TAG` occurrences are stripped from every field, so publisher text cannot forge or close the fence.
- Every field except the description is flattened to a single line, so it cannot forge extra `key: value` rows.
- Fields are truncated (title 300, uploader 200, description 2000 chars).
- The `source_url` is **never** sent: `platform` already identifies the site, and the raw URL would only add attacker-controlled query strings.
- Metadata carrying nothing but `platform` yields `None` — no block, no wasted tokens, no added surface.

A useful side effect: because the model is told to flag disagreement, the summary can note where the video differs from what the publisher claimed.

**Caption-only analysis**: `analyze_captions(captions, api_key)` is a second, separate entry point used when the media could not be downloaded at all (see `docs/backend/run-processing.md`). It is text-only — no file upload, no `_wait_until_active` polling — but goes through the same `_generate_with_retry` backoff + fallback as the media path, and runs under its own `CAPTION_SYSTEM_INSTRUCTION` rather than the normal one.

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

**Transient failures (retry, backoff, fallback)**: a transient error is one whose
`getattr(exc, "code", None)` is in `_TRANSIENT_STATUS` (429/500/502/503/504).
Only those are retried; everything else (400, parse errors, bugs) raises on the
first attempt.

- `_with_backoff(call, attempts, model, operation)` — the one retry primitive.
  Full-jitter exponential backoff: retry *n* sleeps `rand() * min(MAX_DELAY,
  2s * 2**(n-1))`. With defaults (`GEMINI_RETRY_ATTEMPTS=6`,
  `GEMINI_RETRY_MAX_DELAY_SECONDS=20`) the ceilings are 2/4/8/16/20s across 5
  sleeps: at most 50s of sleeping (≈25s on average) plus the six request
  round-trips. Each retry logs at WARNING with operation, status, model,
  attempt and delay — never the exception text or the key. Used for
  `files.upload`, each `files.get` poll in `_wait_until_active`, and
  `generate_content`.
- `_wait_until_active` — each poll goes through `_with_backoff` (full
  `GEMINI_RETRY_ATTEMPTS` budget). A transient poll error is retried; a
  non-transient one raises at once; an exhausted one ends as
  `AnalysisUnavailableError` with **no** re-upload (a busy poll says nothing
  is wrong with the file). The 120s timeout and FAILED →
  `_FileProcessingError` are unchanged; the timeout still counts only the 2s
  poll intervals, so backoff sleeps inside a poll are not charged against it.
- `_generate_with_retry` — `generate_content` on `GEMINI_MODEL` with the full
  budget; if that ends in a transient error **and** `GEMINI_FALLBACK_MODEL` is
  set and differs from the primary, it tries the fallback with the *same*
  `contents` (so the same uploaded file, no second upload) for 2 attempts
  (`_FALLBACK_ATTEMPTS`), and logs at WARNING that the fallback served the
  run. Blank fallback = primary only.
- `analyze_with_retry` keeps its name/signature (`attempts=2` default). Its
  outer loop now re-runs `_analyze` (i.e. re-uploads) **only** for
  `_FileProcessingError` — the upload reached `FAILED` or never became
  `ACTIVE` within 120s, the one case where a fresh upload is the actual fix.
  After the last attempt that `RuntimeError` subclass propagates and
  `ProcessRunUseCase` masks it as before. Any other exception is passed
  through `_as_domain_error` and raised immediately.
- `_as_domain_error` maps a final 429 to "Too many requests right now…" and
  a final 5xx to "Gemini is busy right now…" (`AnalysisUnavailableError`) —
  see `../error-messaging.md`. `analyze_captions` routes through the same
  mapping, and `ProcessRunUseCase` re-raises it out of the caption fallback
  rather than reporting the download error, since "Gemini is busy" is truer
  than "this link couldn't be downloaded".
- `sleep` and `rand` are constructor-injected (defaults `asyncio.sleep` /
  `random.random`); `_wait_until_active` polls with the injected sleep too.

Settings (`backend/app/infrastructure/config.py`, all optional):
`GEMINI_FALLBACK_MODEL` (default blank), `GEMINI_RETRY_ATTEMPTS` (default 6,
clamped to ≥1), `GEMINI_RETRY_MAX_DELAY_SECONDS` (default 20.0). Worst case
with a fallback is well under `WORKER_JOB_TIMEOUT_SECONDS` (600).

**Known issues**:
- An empty or unparseable response (`RuntimeError("Gemini returned an empty
  response.")`, JSON errors) is no longer retried — the old loop retried every
  exception alike. It surfaces as the masked generic failure; if this proves
  common in the logs, add it as a retryable case deliberately.
- ~~`files.get` polls are not wrapped in backoff~~ — resolved 2026-10-02, see
  `_wait_until_active` above.

**Tests**: `backend/tests/infrastructure/ai/test_source_context.py` covers the block builder — field selection, truncation, date formatting, engagement counts, line flattening, fence-forgery stripping, and that the source URL never appears. `backend/tests/infrastructure/ai/test_gemini_engine.py` covers status classification plus the retry design against a fake `genai` client (no network, injected sleep/rand): 503-then-success uploads once, 400 raises without retry, exhausted 503/429 map to the right `AnalysisUnavailableError`, backoff doubling/cap/jitter, fallback used/not used (blank, equal to primary, non-transient), transient upload retry, poll retry (transient-then-ACTIVE, non-transient raises, exhausted maps to `AnalysisUnavailableError` without re-upload), FAILED-file re-upload, settings defaults, stage callbacks, log content, and `analyze_captions` retry + fallback.

## Changelog

- 2026-08-20 · main session · sharpened the summary/markdown prompt bullets so the two fields are distinct reads (short prose abstract vs complete structured notes) instead of the same content in two formats
- 2026-08-21 · main session · classified 429/5xx as AnalysisUnavailableError, and moved the GEMINI_API_KEY hint out of the user-facing message into log_detail
- 2026-08-29 · main session · added `source_context.py` and fed publisher metadata into the prompt as explicitly-untrusted context
- 2026-08-29 · main session · added `analyze_captions` and `CAPTION_SYSTEM_INSTRUCTION` for the caption-only salvage path
- 2026-08-29 · main session · merged dev: routed `analyze_captions` through `_as_domain_error` so a busy-Gemini caption run says so instead of blaming the link
- 2026-09-17 · main session · `analyze`/`analyze_with_retry` take `resolution` (`MEDIA_RESOLUTION_LOW` when supported by the SDK) and `on_usage` (token counts from `usage_metadata`)
- 2026-10-02 · gemini-retry agent · upload once and retry only the failing call; transient-only full-jitter backoff (5 attempts, 2s base, 20s cap), optional `GEMINI_FALLBACK_MODEL` reusing the uploaded file, same helper for `analyze_captions`; outer loop now re-uploads only on FAILED/not-ACTIVE; engine retry tests added
- 2026-10-02 · gemini-retry agent · owner-approved: default `GEMINI_RETRY_ATTEMPTS` raised 5 → 6 (sleep ceilings 2/4/8/16/20s, worst case ~50s, ~25s mean)
- 2026-10-02 · gemini-retry agent · owner-approved: `_wait_until_active` `files.get` polls now use the same transient-only backoff (exhausted → AnalysisUnavailableError, no re-upload); 120s timeout and FAILED handling unchanged; resolved that known issue
- 2026-10-02 · paid-tier integration agent · merged the paid tier into dev: `resolution` (media_resolution in the one `GenerateContentConfig`, so the fallback model gets it too) and `on_usage` (reported once from the successful response, whichever model served it) threaded through the retry/fallback structure
