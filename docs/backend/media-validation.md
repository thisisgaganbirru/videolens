# Media validation & source acquisition

Everything about getting a valid media file onto local disk: upload handling, URL download (with SSRF protection), FFmpeg-based duration checks and normalization.

**Files** (all under `backend/app/infrastructure/media/`)
- `uploads.py` — `save_upload` (streams an uploaded file to disk in 1MB chunks, extension allowlist, size cap), `create_run_dir`/`cleanup_run_dir`.
- `ffmpeg.py` — `_media_binary` (resolves the ffmpeg/ffprobe path, either from `FFMPEG_LOCATION` or `PATH`), `probe_duration_seconds`, `enforce_duration_cap`, `normalize_media` (re-encodes to H.264/AAC mp4 if a video stream is present, else mp3), `_has_video_stream`.
- `ytdlp_downloader.py` — `_validate_public_url` (**SSRF guard**), `_cookie_options`, `download_url`.
- `service.py` — `MediaService`, the single adapter that composes all three modules above into the `MediaProcessor` port the use cases depend on.

**SSRF protection**: `_validate_public_url` in `ytdlp_downloader.py` parses the URL, requires `http`/`https` with no embedded credentials, then does a real DNS resolution (`socket.getaddrinfo`) and checks **every** resolved address is a global IP (`ipaddress.ip_address(...).is_global`) — rejects private/local/link-local targets *before* yt-dlp ever touches the URL. This is the load-bearing check that stops someone submitting `http://169.254.169.254/...` or a `localhost` URL to reach internal infra.

**Limits enforced**: file extension (`.mp3`/`.mp4`/`.mov` only), `MAX_FILE_SIZE_MB` (both during streamed upload and post-download for URL sources), `MAX_DURATION_SECONDS` via `enforce_duration_cap` (checked once for uploads, checked again after download for URL/S3 sources since those weren't probed synchronously by the request handler).

**yt-dlp cookies**: exactly one of `YTDLP_COOKIES_FILE` or `YTDLP_COOKIES_FROM_BROWSER` may be configured — both set raises `MediaValidationError`. Needed for login-gated sources (Instagram in particular); the download-error message is rewritten with cookie-setup guidance when yt-dlp reports Instagram returned an empty response.

**Source metadata**: `download_url` also builds a `domain.entities.SourceMetadata` from the same `extract_info()` call already needed for the download itself (`platform` from `extractor_key`, plus `title`/`uploader`/`uploader_url`/`description`/`upload_date`/`like_count`/`view_count`/`comment_count`, all `dict.get()`-based so missing fields are just `None`) and attaches it to the returned `SavedUpload`. This is platform post metadata, distinct from the Gemini-generated `VideoAnalysis` — see `docs/backend/run-processing.md` for how it's persisted onto the `Run`. File uploads (`uploads.save_upload`) never set this field.

**Known issue / non-issue**: none currently identified beyond what's already handled — this is one of the more defensively-written areas of the codebase.

**Tests**: `backend/tests/infrastructure/media/test_ytdlp_downloader.py` covers URL validation (including the SSRF rejection case, via a mocked `socket.getaddrinfo`), cookie-option building, and download-error message rewriting. No test coverage for `ffmpeg.py` or `uploads.py` directly (they require an actual ffmpeg binary / real file I/O).
