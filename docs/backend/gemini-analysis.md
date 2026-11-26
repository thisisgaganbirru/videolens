# Gemini analysis integration

Uploads the normalized media file to Gemini, waits for it to finish processing, and requests a structured analysis (transcript, on-screen text, summary, markdown notes) matching the `VideoAnalysis` schema directly.

**Files**
- `backend/app/infrastructure/ai/gemini_engine.py` — `GeminiEngine`, implements the `AnalysisEngine` port.
- `backend/app/infrastructure/ai/source_context.py` — `build_source_context`, renders a run's `SourceMetadata` into the prompt block described below. Deliberately SDK-free so it can be tested without a Gemini client.
- `backend/app/domain/entities.py` — `VideoAnalysis`/`TranscriptSegment`/`ScreenTextSegment`, passed directly as `response_schema` to Gemini's structured-output config (no separate parsing/mapping layer — Gemini is asked to return exactly this shape).

**Flow**: `_analyze` uploads the file **once** (`client.aio.files.upload`, itself wrapped in the transient-only backoff below), polls `_wait_until_active` every 2s up to a 300s timeout for Gemini to finish processing the upload, then calls `generate_content` through `_generate_with_retry` with the fixed `SYSTEM_INSTRUCTION` prompt, the media part, an optional source-metadata block, and the `VideoAnalysis` response schema. Only the failing call is retried — a 503 from `generate_content` never re-uploads the file. The result returns as soon as the response is parsed; the uploaded Gemini file is deleted afterwards in a background task scheduled from a `finally` block (best-effort, failure swallowed), which then releases the client. See "Background clean-up" below. `analyze_with_retry` (the port method) wraps `_analyze`; see "Transient failures" for what its outer loop still does.

**Video sampling and resolution** (2026-11-26; carousel interaction 2026-11-27): two optional settings change what Gemini sees of a video, for a single video and for a carousel's video slides alike. Both unset sends exactly the request the engine sent before they existed: the bare uploaded file for every video, and no `media_resolution` on the config, so Gemini uses its own defaults.

- `GEMINI_VIDEO_FPS` (default 0 = Gemini's 1 fps; validated to `[0, 24]`, Gemini accepts `(0, 24]`). Set, `_media_part` wraps every video upload (mime `video/*`: a single video, or each video slide of a carousel) in `types.Part(file_data=..., video_metadata=VideoMetadata(fps=...))`. Audio (`normalized.mp3`) and image slides never carry it. The mime is the upload's own `mime_type`, which the SDK sets from the file extension (`mimetypes.guess_type`) before uploading; normalization always writes `.mp4` for video (`normalize_media`: `normalized.mp4`, `normalized-NN.mp4` for slides), `.mp3` for audio and `.jpg` for image slides, so a video is always `video/mp4`. A file without a `video/*` mime goes in unwrapped, which is the place to look if fps ever seems to have no effect. More frames shrink the window in which brief text can fall between two samples (under 1s at 1 fps, under 0.5s at 2 fps); they do not make the text more legible.
- `GEMINI_MEDIA_RESOLUTION` (blank, `low`, `medium` or `high`; anything else refuses to start). Where it goes depends on the run:
  - A single file: on the whole request (`GenerateContentConfig.media_resolution`, `_MEDIA_RESOLUTIONS`), which works on every model. The part stays the bare upload unless fps applies.
  - A carousel: never request-wide. Its image slides already carry a per-part level (`GEMINI_SLIDE_IMAGE_RESOLUTION`, below), and the engine never sends both in one request. Google has said a per-part value "overrides any global configuration for a specific part" (quoted by the session that wrote the setting); the media-resolution page as fetched on 2026-11-27 did not state it, and the combination has never been sent live, so it is avoided rather than relied on. `GEMINI_MEDIA_RESOLUTION` goes instead on each **video** slide's part (`PartMediaResolution`, the same level name), next to its `VideoMetadata` when fps is set too. Image slides keep their own level, so per part wins for them by construction; with `GEMINI_SLIDE_IMAGE_RESOLUTION` blank they get the model's default, not this setting.
  - Captions runs never carry it.

  Per-part resolution on a *video* part has not been exercised against live Gemini (per-part on image slides has, 2026-11-26); per-part needs Gemini 3 or later, so with an older `GEMINI_FALLBACK_MODEL` leave it blank for carousels.

Google's numbers for Gemini 3 and 4 models (media-resolution docs, read 2026-11-26): video is 70 tokens a frame at the default, `low` and `medium`, 280 at `high` (recommended "only when the use case involves reading dense text (OCR)"); audio is 25 tokens a second at every level. Input tokens for a run, video plus audio:

| Run | Default | high, 1 fps | high, 2 fps |
| --- | --- | --- | --- |
| 180s | 17.1k | 54.9k | 105.3k |
| 600s | 57k | 183k | 351k |

`gemini-3.6-flash` input is $0.75 per 1M tokens through 2026-12-31 and $1.50 from 2027-01-01. Paid shared-key runs skip `DAILY_RUN_CAP` and may be 600s, so price a change here against the 600s row too. The parts and the config are built once per run, so the fallback model gets the same ones. A carousel's video slide costs the same per frame as a single video at the same settings.

Not used: Gemini's opt-in "agentic" video processing. It loads only the parts of a video the model decides it needs, which is the opposite of reading every on-screen text, Google recommends static processing for clips under 5 minutes, and it exists only on the Interactions API.

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
  is wrong with the file). The timeout (300s since longer runs were allowed; it was 120s) and FAILED →
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
  `ACTIVE` within 300s, the one case where a fresh upload is the actual fix.
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
clamped to ≥1), `GEMINI_RETRY_MAX_DELAY_SECONDS` (default 20.0). `GEMINI_VIDEO_FPS`
and `GEMINI_MEDIA_RESOLUTION` (default off; above) apply to single videos and to a
carousel's video slides. `GEMINI_SLIDE_IMAGE_RESOLUTION` (default `high`) applies to
multi-slide posts only; see below. Worst case
with a fallback is well under `WORKER_JOB_TIMEOUT_SECONDS` (600).

**Known issues**:
- An empty or unparseable response (`RuntimeError("Gemini returned an empty
  response.")`, JSON errors) is no longer retried — the old loop retried every
  exception alike. It surfaces as the masked generic failure; if this proves
  common in the logs, add it as a retryable case deliberately.
- ~~`files.get` polls are not wrapped in backoff~~ — resolved 2026-10-02, see
  `_wait_until_active` above.

**Tests**: `backend/tests/infrastructure/ai/test_source_context.py` covers the block builder — field selection, truncation, date formatting, engagement counts, line flattening, fence-forgery stripping, and that the source URL never appears. `backend/tests/infrastructure/ai/test_gemini_engine.py` covers status classification plus the retry design against a fake `genai` client (no network, injected sleep/rand): 503-then-success uploads once, 400 raises without retry, exhausted 503/429 map to the right `AnalysisUnavailableError`, backoff doubling/cap/jitter, fallback used/not used (blank, equal to primary, non-transient), transient upload retry, poll retry (transient-then-ACTIVE, non-transient raises, exhausted maps to `AnalysisUnavailableError` without re-upload), FAILED-file re-upload, settings defaults, stage callbacks, log content, and `analyze_captions` retry + fallback. `VideoSamplingTests` covers the two video settings: unset sends the bare file and no resolution, fps wraps video but not audio, each resolution reaches the config, the fallback reuses the same part and config, and captions never carry them; `SlideVideoSamplingTests` in `test_gemini_slides.py` covers carousels: unset leaves the post as before, fps reaches video slides only, the resolution goes per part on video slides and never request-wide, and a blank image level does not inherit it; `tests/infrastructure/test_config.py` covers their validation.

## Multi-slide posts (2026-11-26)

`analyze_slides_with_retry(slides, ...)` analyzes a whole carousel in one request. `_analyze_files` (shared with the single-file `_analyze`) uploads every slide with the usual transient backoff and waits for each to be ACTIVE, four at a time (`_upload_all`, `_UPLOAD_CONCURRENCY`; up to 20 one after another was 10-20 s before analysis could start), then and sends `["Slide 1 of N (image):", file1, "Slide 2 of N (video):", file2, ..., intro, source context]`, so each label sits right before its own file and the media still comes before any publisher text. Every upload is deleted however the call ends, including the ones before an upload that failed. The deletes run concurrently, four at a time (`_delete_all`, same `_UPLOAD_CONCURRENCY` cap), in the background after the result has gone back to the run ("Background clean-up" below); one at a time and awaited they were ~0.5 s each in front of every result (~4.2 s for an 8-slide post, measured live). A failed delete is swallowed and does not stop the others. A slide Gemini fails to process re-uploads the whole post once (`_with_reupload`, the loop `analyze_with_retry` already had).

The system instruction is `CAROUSEL_SYSTEM_INSTRUCTION`: the base instruction plus rules for reading image slides in full (below), attributing every segment to its slide (`slide`, 1-based), restarting timestamps at 0 on each slide (both 0 on an image slide) and following slide order in the notes. `TranscriptSegment` and `ScreenTextSegment` gained `slide: Optional[int]`; it is model output like the timestamps, not a server fact. `_checked_slides` clears a number outside 1..N, and on a single file clears every one (the single-file instruction also says to leave it unset), returning the same object when nothing changed. Images are re-encoded to at most 2048 px first (`media-validation.md`); Instagram's largest are 1440 px and nothing is enlarged, so the re-encode does not lose detail.

**Every line of an image slide (fixed 2026-11-26, live run)**. On an 8-slide post whose slides each carried a headline, a subtitle and a block of small monospace terminal text, the segments held only the headline and subtitle (about 120 characters a slide) and the flat `screen_text` was a 321-character selection. Three causes, three fixes:
- The prompt. The base instruction asks for "the important on-screen text", and the carousel rule only asked for "at least one" segment per slide, which the model read as one short one. The carousel instruction now asks for exactly one `screen_text_segments` entry per image slide holding every legible line in reading order, keeping line breaks, small print, code and terminal text included, copied as written and not summarised, with text too small to read left out rather than guessed (the base "do not invent text" rule stays). The single-file instruction is unchanged.
- The image resolution Gemini reads at. No `media_resolution` was set, and Gemini 3's default for an image is `high` (about 1120 tokens). Each image slide's part now carries a per-part `media_resolution` from `GEMINI_SLIDE_IMAGE_RESOLUTION` (default `high`, about 1120 tokens; `ultra_high`, about 2240 tokens and a per-part-only level, was the default until later the same day; blank = the model's default; `low`/`medium` also accepted, anything else refuses to start). The default moved to `high` after a live run on an 8-slide carousel read the same text at both levels (6150 vs 6147 characters) and Gemini answered about 4 s sooner at `high`. `_media_part` builds the `types.Part` from the upload's `uri` and `mime_type`, which is what the SDK does with a bare `File` minus the resolution. Video slides and single files are sent as the upload itself unless `GEMINI_VIDEO_FPS` or `GEMINI_MEDIA_RESOLUTION` is set ("Video sampling and resolution" above). A 20-slide image post is about 20 × 1120 tokens at `high` (20 × 2240 at `ultra_high`). Gemini's docs call per-part resolution experimental and list it for Gemini 3 and later only; with an older `GEMINI_FALLBACK_MODEL`, or if a model ever rejects it, set the variable blank (not tested against an older model).
- The flat text. `_screen_text_from_segments` rebuilds a post's `screen_text` from its segments (their text in the order returned, a blank line between entries), so the two always agree; with no segment text the model's own is kept. A single file keeps the model's `screen_text`, because a video's segments repeat text that stays on screen.

Not verified against live Gemini when written: the orchestrator's re-run of the same post is the check.

## Background clean-up (2026-11-26)

Owner decision: once Gemini has answered, the person sees the result; deleting the uploads from Gemini's servers happens behind it. Measured before the change: the awaited deletes added ~1.2 s to a carousel result, and on one run a single DELETE took 7 s.

- **Flow.** `_analyze_files` returns as soon as `generate_content` returns and `_parse` succeeds, so `ProcessRunUseCase` saves the run as complete without waiting. Its `finally` calls `_schedule_cleanup` (synchronous, so it also runs while a cancellation unwinds), which starts one task per call: `_cleanup` deletes every upload that happened (`_delete_all`, four at a time) and then calls `_release`.
- **Who releases the client.** The background task, after its deletes, never before: a per-BYOK client is not closed under a delete still in flight. The shared server-key client is never closed (`_release` is a no-op for it). A task is scheduled even with nothing to delete, so a BYOK client is still closed when an upload failed.
- **Every path.** Success, a failed `generate_content`, a parse failure, a failed upload (the uploads before it), and a cancelled run (worker SIGTERM, job timeout) all go through the same `finally`. The task is separate from the run's task, so cancelling the run does not cancel its deletes. Each attempt of `_with_reupload` (`analyze_with_retry`, `analyze_slides_with_retry`) schedules its own one task, so a run has at most two.
- **Task tracking.** `GeminiEngine._cleanups` is a set holding a strong reference to every running clean-up (the event loop keeps only weak ones); a done callback removes it.
- **Failures.** A failed delete is swallowed and does not stop the others. One info line gives the count and the exception types only, never a file name or the error text. Anything else in `_cleanup` is swallowed at debug.
- **Shutdown.** `GeminiEngine.drain(timeout)` waits up to `timeout` seconds for the running clean-ups, logs at info how many are still running, and returns without raising or cancelling them. `Container.close()` calls `drain(timeout=5.0)` right after the job queue closes; both the API lifespan shutdown and the arq worker's `on_shutdown` already go through `Container.close()`, so neither hook changed. An upload not deleted by then (a hard kill, a delete slower than 5 s at shutdown) expires on Gemini's side after 48 hours.
- **Concurrency cap.** Four deletes at a time per call, as before; N runs finishing together can have up to 4N deletes in flight on the shared client.
- **Upload cancelled mid-flight.** An upload whose `files.upload` call was itself cancelled never returned a name, so it cannot be deleted; it expires after 48 h (unchanged from before).

**Tests** (`BackgroundCleanupTests` in `tests/infrastructure/ai/test_gemini_slides.py`): the result returns while gated deletes are still blocked; all nine uploads deleted once released and drained; at most four in flight; deletes on a failed generate, on a parse failure and on a cancelled run; `_release` only after every delete; a BYOK client closed only after its deletes; `drain` gives up after its timeout without raising or cancelling; a failed delete is logged without its file name. Existing tests that assert deletes or a closed client `await engine.drain()` first.

## SDK version and API version

`google-genai` is on 3.x (3.6.1 in the lock). The 3.0 release changed two
defaults; this engine neutralises the one that matters:

- **API version.** 3.0 moved the Gemini Developer API default from `v1beta` to
  `v1`. `gemini_engine.py` pins `types.HttpOptions(api_version="v1beta")` on
  both the shared client and every bring-your-own-key client, so the upgrade did
  not change which API is called. `v1` lacks the `-latest` model aliases, some
  preview models, the Live API and context caching. Dropping the pin is a
  separate change that needs a real run against `GEMINI_MODEL` on dev first.
- **HTTP client.** The SDK now uses `httpx2` (and `truststore`, the OS trust
  store) instead of `httpx`. Nothing in `backend/app` imports `httpx` or
  catches its exceptions, so this is internal to the SDK.

## Changelog

- 2026-08-20 · main session · sharpened the summary/markdown prompt bullets so the two fields are distinct reads (short prose abstract vs complete structured notes) instead of the same content in two formats
- 2026-08-21 · main session · classified 429/5xx as AnalysisUnavailableError, and moved the GEMINI_API_KEY hint out of the user-facing message into log_detail
- 2026-08-29 · main session · added `source_context.py` and fed publisher metadata into the prompt as explicitly-untrusted context
- 2026-08-29 · main session · added `analyze_captions` and `CAPTION_SYSTEM_INSTRUCTION` for the caption-only salvage path
- 2026-08-29 · main session · merged dev: routed `analyze_captions` through `_as_domain_error` so a busy-Gemini caption run says so instead of blaming the link
- 2026-10-02 · gemini-retry agent · upload once and retry only the failing call; transient-only full-jitter backoff (5 attempts, 2s base, 20s cap), optional `GEMINI_FALLBACK_MODEL` reusing the uploaded file, same helper for `analyze_captions`; outer loop now re-uploads only on FAILED/not-ACTIVE; engine retry tests added
- 2026-10-02 · gemini-retry agent · owner-approved: default `GEMINI_RETRY_ATTEMPTS` raised 5 → 6 (sleep ceilings 2/4/8/16/20s, worst case ~50s, ~25s mean)
- 2026-10-02 · gemini-retry agent · owner-approved: `_wait_until_active` `files.get` polls now use the same transient-only backoff (exhausted → AnalysisUnavailableError, no re-upload); 120s timeout and FAILED handling unchanged; resolved that known issue
- 2026-11-18 · claude (session 01FVkcsidCXWo1CtwAtdwVHV) · google-genai 2.34.0 -> 3.4.0 (owner-approved, from Dependabot #137); pinned `api_version="v1beta"` on every client so the 3.0 default switch to `v1` changes nothing; httpx -> httpx2 is internal to the SDK. 1003 backend tests pass; not exercised against live Gemini before merge
- 2026-11-26 · deps agent · google-genai 3.4.0 -> 3.6.1 (from Dependabot #151, minor); `api_version="v1beta"` pin and `client.close()` / `client.aio.aclose()` unchanged and still present. 1279 backend tests pass; not exercised against live Gemini
- 2026-11-26 · Claude (session ccr-3d42b168) · `analyze_slides_with_retry`: one request per carousel with labelled slide parts, `CAROUSEL_SYSTEM_INSTRUCTION`, `slide` on segments checked by `_checked_slides`; `_analyze` now goes through the shared `_analyze_files`. Not exercised against live Gemini
- 2026-11-26 · Claude (session ccr-3d42b168) · review fix: slides upload and wait for ACTIVE four at a time (`_upload_all`), uploads kept in slide order for the request
- 2026-11-26 · Claude (backend agent) · restored this doc (b2d54e0 had truncated it to its changelog line by accident) and kept dev's deps line; image slides read in full: carousel prompt asks for every legible line per slide, image parts carry `media_resolution` (`GEMINI_SLIDE_IMAGE_RESOLUTION`, default `ultra_high`), flat `screen_text` rebuilt from the segments for posts. Not exercised against live Gemini
- 2026-11-26 · Claude (backend agent) · concurrent clean-up: _analyze_files deletes its uploads four at a time (_delete_all) instead of one by one, still awaited before _release; ~4 s off an 8-slide post's result. Tests: deletes overlap (peak 4), all deleted before release on success and on a failed generate, a failed delete is swallowed. Not exercised against live Gemini
- 2026-11-26 · Claude (backend agent) · upload deletes off the critical path: the result returns once Gemini's answer is parsed; a background task per call deletes the uploads (four at a time) and then releases the client; `_cleanups` keeps the tasks, `drain(timeout)` runs from `Container.close()` (API lifespan and worker `on_shutdown`, 5 s), leftovers expire on Gemini after 48 h. Supersedes the "still awaited before _release" line above. `GEMINI_SLIDE_IMAGE_RESOLUTION` default `ultra_high` -> `high` (same text live, ~4 s faster). Not exercised against live Gemini
- 2026-11-26 · claude · added `GEMINI_VIDEO_FPS` and `GEMINI_MEDIA_RESOLUTION` (both off by default, request unchanged when unset) so frame rate and per-frame tokens can be A/B tested for on-screen text; token and price figures checked against Google's docs; fixed the stale 120s ACTIVE-timeout references (the code has used 300s)
- 2026-11-27 · backend agent · rebased video fps/media resolution settings onto 2.4.0 carousel: `_media_part` (replaces `_part_at`) applies `GEMINI_VIDEO_FPS` to every video part including carousel video slides; `GEMINI_MEDIA_RESOLUTION` stays request-wide on single files and goes per part on carousel video slides only, never request-wide next to the image slides' per-part level; tests in `SlideVideoSamplingTests`
