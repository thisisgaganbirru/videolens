# Media validation & source acquisition

Everything about getting a valid media file onto local disk: upload handling, URL download (with SSRF protection), FFmpeg-based duration checks and normalization.

**Files** (all under `backend/app/infrastructure/media/`)
- `uploads.py` — `save_upload` (streams an uploaded file to disk in 1MB chunks, extension allowlist, size cap), `create_run_dir`/`cleanup_run_dir`.
- `ffmpeg.py` — `_media_binary` (resolves the ffmpeg/ffprobe path, either from `FFMPEG_LOCATION` or `PATH`), `probe_duration_seconds`, `enforce_duration_cap`, `normalize_media` (re-encodes to H.264/AAC mp4 if a video stream is present, else mp3), `_has_video_stream`.
- `net.py` — `validate_public_url` (**SSRF guard**), shared by every resolver.
- `ytdlp_downloader.py` — `_cookie_options`, `download_url` (the yt-dlp fetch itself).
- `captions.py` — `fetch_captions`, the subtitle salvage path used when every resolver has failed.
- `resolvers/` — one route per file plus the chain that orders them: `ytdlp.py` (`YtDlpResolver`), `direct_http.py` (`DirectHttpResolver`), `chain.py` (`ResolverChain`).
- `service.py` — `MediaService`, the single adapter that composes all of the above into the `MediaProcessor` port the use cases depend on.

**Resolver chain**: `MediaService.download_url` no longer calls yt-dlp directly — it delegates to a `ResolverChain` of `domain.ports.SourceResolver` implementations, tried in order. Each resolver declares `can_handle(url)` and is skipped when it says no; a resolver that raises `MediaValidationError` is treated as "this route did not work" and the chain moves on, while any other exception propagates immediately (a bug must not be silently retried away). Current order:

| # | Resolver | Claims | Notes |
|---|---|---|---|
| 1 | `YtDlpResolver` | every URL | Primary path; yt-dlp's generic extractor is itself a fallback for plain links. The only resolver that returns `SourceMetadata`. |
| 2 | `DirectHttpResolver` | URLs whose path ends in an allowed extension | Plain stdlib HTTP GET. Recovers links yt-dlp declines (unknown host, odd content type, stale extractor). No metadata. |

Ordering yt-dlp first is deliberate: nothing that works today changes behaviour, and the fallback only ever runs after the primary has already failed. When every route fails, the **first** resolver's error is the one raised — it is the primary path and carries the curated guidance (the Instagram cookie message), whereas a fallback's failure is usually a bare 404. Adding a source is a new resolver plus one line in `MediaService`; `MediaProcessor` and `ProcessRunUseCase` are untouched.

`DirectHttpResolver` builds its opener with `_ValidatingRedirectHandler`, which re-runs `validate_public_url` on **every redirect hop** — validating only the submitted URL would let a public host bounce the fetch to `169.254.169.254`. It enforces `MAX_FILE_SIZE_MB` twice: against `Content-Length` before reading a byte, and again while streaming (a server can lie or omit the header). It uses `urllib.request` rather than `httpx` because httpx is only present transitively via `google-genai`; taking a direct dependency would mean re-pinning the hash-locked `requirements.txt` for a fallback path.

**Caption recovery** (`captions.py`): `fetch_captions` is not a resolver — it returns a transcript, not media, so it cannot satisfy `SourceResolver`. It is reached from `ProcessRunUseCase` only after the whole chain has failed. It prefers publisher-written subtitles over auto-captions, prefers `json3`/`vtt`/`srt` in that order (least parsing first), falls back to any available language rather than giving up, and strips cue scaffolding down to plain text — collapsing the duplicated rolling-window lines auto-captions emit, which would otherwise triple the token cost and read as a stutter. It **re-applies `MAX_DURATION_SECONDS`** from the info dict: the duration cap is a product policy about how much media gets analyzed, and a caption track must not become a way around it. Every expected miss returns `None` rather than raising, because the caller is already handling a failed download and needs a yes/no, not a second error to reconcile.

`_source_metadata_from_info` was extracted out of `ytdlp_downloader.download_url` so both paths build `SourceMetadata` identically — the publisher's post metadata is available from `extract_info` whether or not the media bytes are.

**SSRF protection**: `validate_public_url` in `net.py` parses the URL, requires `http`/`https` with no embedded credentials, then does a real DNS resolution (`socket.getaddrinfo`) and checks **every** resolved address is a global IP (`ipaddress.ip_address(...).is_global`) — rejects private/local/link-local targets *before* any resolver touches the URL. This is the load-bearing check that stops someone submitting `http://169.254.169.254/...` or a `localhost` URL to reach internal infra. It lives in its own module precisely so there is one copy: a second implementation that drifts is how a fallback route ends up reaching an address the primary route refuses.

**Limits enforced**: file extension (`.mp3`/`.mp4`/`.mov` only), `MAX_FILE_SIZE_MB` (both during streamed upload and post-download for URL sources), `MAX_DURATION_SECONDS` via `enforce_duration_cap` (checked once for uploads, checked again after download for URL/S3 sources since those weren't probed synchronously by the request handler).

**yt-dlp cookies**: exactly one of `YTDLP_COOKIES_FILE` or `YTDLP_COOKIES_FROM_BROWSER` may be configured — both set raises `MediaValidationError`. Needed for login-gated sources (Instagram in particular); the download-error message is rewritten with cookie-setup guidance when yt-dlp reports Instagram returned an empty response.

**Source metadata**: `download_url` also builds a `domain.entities.SourceMetadata` from the same `extract_info()` call already needed for the download itself (`platform` from `extractor_key`, plus `title`/`uploader`/`uploader_url`/`description`/`upload_date`/`like_count`/`view_count`/`comment_count`, all `dict.get()`-based so missing fields are just `None`) and attaches it to the returned `SavedUpload`. This is platform post metadata, distinct from the Gemini-generated `VideoAnalysis` — see `docs/backend/run-processing.md` for how it's persisted onto the `Run`. File uploads (`uploads.save_upload`) never set this field.

**Known issue / non-issue**: none currently identified beyond what's already handled — this is one of the more defensively-written areas of the codebase.

**Tests** (all under `backend/tests/infrastructure/media/`)
- `test_net.py` — the SSRF guard: scheme, embedded credentials, URL length, unresolvable host, and the case where only the *second* resolved address is private.
- `test_ytdlp_downloader.py` — cookie-option building, download-error message rewriting, and the `SourceMetadata` mapping.
- `test_resolver_chain.py` — order, fall-through, skipping non-claiming resolvers, which error surfaces, metadata preservation, and that a non-`MediaValidationError` is not swallowed.
- `test_captions.py` — cue/json3/XML parsing, rolling-duplicate collapsing, and track/format selection preferences.
- `test_direct_http_resolver.py` — `can_handle` boundaries, both size-cap paths, HTTP status reporting, empty body, run-dir cleanup on failure, that transport errors are not surfaced verbatim, and the private-address redirect refusal.

No test coverage for `ffmpeg.py` or `uploads.py` directly (they require an actual ffmpeg binary / real file I/O).

## Changelog
- 2026-08-29 · main session · extracted the SSRF guard into `net.py`; put `download_url` behind an ordered `ResolverChain` and added `DirectHttpResolver` as the fallback route
- 2026-08-29 · main session · added `captions.py` (subtitle salvage) and shared `_source_metadata_from_info` between the download and caption paths
