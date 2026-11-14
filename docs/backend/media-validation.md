# Media validation & source acquisition

Everything about getting a valid media file onto local disk: upload handling, URL download (with SSRF protection), FFmpeg-based duration checks and normalization.

**Files** (all under `backend/app/infrastructure/media/`)
- `uploads.py` — `save_upload` (streams an uploaded file to disk in 1MB chunks, extension allowlist, size cap), `create_run_dir`/`cleanup_run_dir`, `validate_temp_dir` (startup guard, below).
- `ffmpeg.py` — `_media_binary` (resolves the ffmpeg/ffprobe path, either from `FFMPEG_LOCATION` or `PATH`), `probe_duration_seconds`, `enforce_duration_cap`, `normalize_media` (re-encodes to H.264/AAC mp4 if a video stream is present, else mp3), `_has_video_stream`. `_has_video_stream` reads only the first CSV field of ffprobe's output: a stream with side data (phone rotation matrix, the ambient-viewing block on Instagram VP9 reels) prints `video,` not `video`, and the old exact match sent those files down the `-vn` mp3 path, losing the picture, or failing with "Output file does not contain any stream" when there was no audio either. Fixed 2026-10-28; `tests/infrastructure/media/test_ffmpeg.py`.
- `net.py` — `validate_public_url` (**SSRF guard**), shared by every resolver.
- `ytdlp_downloader.py` — `_cookie_options`, `download_url` (the yt-dlp fetch itself).
- `captions.py` — `fetch_captions`, the subtitle salvage path used when every resolver has failed.
- `resolvers/` — one route per file plus the chain that orders them: `ytdlp.py` (`YtDlpResolver`), `direct_http.py` (`DirectHttpResolver`), `chain.py` (`ResolverChain`).
- `thumbnails.py` — history poster + display size (Phase 5a): `thumbnail_urls_from_info`, `dimensions_from_info`, `parse_video_dimensions`/`probe_dimensions` (ffprobe, rotation-aware), `fetch_image` (SSRF-guarded), `extract_frame`, `encode_thumbnail`, `build_thumbnail`. See the section below.
- `service.py` — `MediaService`, the single adapter that composes all of the above into the `MediaProcessor` port the use cases depend on.

**Resolver chain**: `MediaService.download_url` no longer calls yt-dlp directly — it delegates to a `ResolverChain` of `domain.ports.SourceResolver` implementations, tried in order. Each resolver declares `can_handle(url)` and is skipped when it says no; a resolver that raises `MediaValidationError` is treated as "this route did not work" and the chain moves on, while any other exception propagates immediately (a bug must not be silently retried away). Current order:

| # | Resolver | Claims | Notes |
|---|---|---|---|
| 1 | `YtDlpResolver` | every URL | Primary path; yt-dlp's generic extractor is itself a fallback for plain links. The only resolver that returns `SourceMetadata`. |
| 2 | `DirectHttpResolver` | URLs whose path ends in an allowed extension | Plain stdlib HTTP GET. Recovers links yt-dlp declines (unknown host, odd content type, stale extractor). No metadata. |

Ordering yt-dlp first is deliberate: nothing that works today changes behaviour, and the fallback only ever runs after the primary has already failed. When every route fails, the **first** resolver's error is the one raised — it is the primary path and carries the curated guidance (the Instagram cookie message), whereas a fallback's failure is usually a bare 404. Adding a source is a new resolver plus one line in `MediaService`; `MediaProcessor` and `ProcessRunUseCase` are untouched.

`DirectHttpResolver` builds its opener with `_ValidatingRedirectHandler` (since Phase 5a this lives in `net.py` as `ValidatingRedirectHandler`, re-exported under the old name, so the thumbnail fetch shares the one copy), which re-runs `validate_public_url` on **every redirect hop** — validating only the submitted URL would let a public host bounce the fetch to `169.254.169.254`. It enforces `MAX_FILE_SIZE_MB` twice: against `Content-Length` before reading a byte, and again while streaming (a server can lie or omit the header). It uses `urllib.request` rather than `httpx` because httpx is only present transitively via `google-genai`; taking a direct dependency would mean re-pinning the hash-locked `requirements.txt` for a fallback path.

**Caption recovery** (`captions.py`): `fetch_captions` is not a resolver — it returns a transcript, not media, so it cannot satisfy `SourceResolver`. It is reached from `ProcessRunUseCase` only after the whole chain has failed. It prefers publisher-written subtitles over auto-captions, prefers `json3`/`vtt`/`srt` in that order (least parsing first), falls back to any available language rather than giving up, and strips cue scaffolding down to plain text — collapsing the duplicated rolling-window lines auto-captions emit, which would otherwise triple the token cost and read as a stutter. It **re-applies the run's duration limit** (`MAX_DURATION_SECONDS`, or the signed-in BYOK value for that run) from the info dict: the duration cap is a product policy about how much media gets analyzed, and a caption track must not become a way around it. Every expected miss returns `None` rather than raising, because the caller is already handling a failed download and needs a yes/no, not a second error to reconcile.

`_source_metadata_from_info` was extracted out of `ytdlp_downloader.download_url` so both paths build `SourceMetadata` identically — the publisher's post metadata is available from `extract_info` whether or not the media bytes are.

**SSRF protection**: `validate_public_url` in `net.py` parses the URL, requires `http`/`https` with no embedded credentials, then does a real DNS resolution (`socket.getaddrinfo`) and checks **every** resolved address with `is_public_address` — `is_global`, not multicast, and for IPv6 not a translation form (IPv4-mapped, 6to4, Teredo, NAT64 `64:ff9b::/96` and `64:ff9b:1::/48`) wrapping a non-public IPv4 address; `ipaddress` alone calls `64:ff9b::7f00:1` global — rejecting private/local/link-local targets *before* any resolver touches the URL. It returns the approved address.

**Pinned connections (2026-11-07)**: checking a name and then letting urllib resolve it again is the DNS-rebinding hole (the name answers a public address to the check and a private one to the fetch). `build_public_opener()` is the one urllib opener for outbound fetches (`DirectHttpResolver`, the thumbnail fetch): its `PublicHTTPHandler`/`PublicHTTPSHandler` run the check for every request they open — the first one and every redirect hop — and then connect `PinnedHTTPConnection`/`PinnedHTTPSConnection` to the *approved address*, with the URL's hostname kept for the Host header and the TLS server name, so certificate verification is unchanged. Through an explicit proxy (`HTTP(S)_PROXY`) the URL is still checked but the connection is not pinned, because the proxy does the resolving.

**yt-dlp is outside the pinning**: it does its own resolution, redirects and sub-requests. Only the submitted URL is checked before it runs. The mitigation is at the network layer: run the worker with egress that cannot reach internal ranges, or set `HTTP_PROXY`/`HTTPS_PROXY` to a validating forward proxy (yt-dlp and urllib both honour them). This is the load-bearing check that stops someone submitting `http://169.254.169.254/...` or a `localhost` URL to reach internal infra. It lives in its own module precisely so there is one copy: a second implementation that drifts is how a fallback route ends up reaching an address the primary route refuses.

**Limits per caller (2026-11-13)**: the size and duration limits are no longer read from `Settings` at each check. `EntitlementResolver.media_limits(principal, byok=...)` (`application/entitlements.py`) returns a `domain.entitlements.MediaLimits` for the caller: signed in (JWT or account API key) **and** sending `X-Gemini-Api-Key` gets `SIGNED_IN_BYOK_MAX_DURATION_SECONDS` / `SIGNED_IN_BYOK_MAX_FILE_SIZE_MB` (600 s / 500 MB); everyone else, anonymous BYOK included, gets `MAX_DURATION_SECONDS` / `MAX_FILE_SIZE_MB` (180 s / 200 MB). A bigger value at or below the standard one is floored to the standard one. Every enforcement point takes that object as `limits=`: `save_upload` (streamed size), `enforce_duration_cap`, `download_url` (yt-dlp `max_filesize`, the progress hook and the post-download check), `DirectHttpResolver` (Content-Length and streamed size), and `fetch_captions` (the caption track's duration, formerly a direct `settings.max_duration_seconds` read). `infrastructure/media/limits.py`'s `effective_limits` falls back to the standard set when a caller passes `None`, so older call sites and tests keep today's behaviour. The run carries its limits to the worker (`job-queue.md`), so the worker checks the same numbers the API admitted. Messages come from `duration_over_limit_message` / `size_over_limit_message` in `domain/entitlements.py`: same status and `{detail}` shape, plus a hint when a bigger tier would have fit ("Sign in and add your own Gemini key for videos up to 10:00."; "Sign in" for anonymous BYOK, "Add your own Gemini key" for signed in without one). The yt-dlp post-download sentence is now "That video is over the 200MB limit." instead of "Download exceeds the 200 MB size limit.". `GET /api/limits` reports both sets. Since the paid plan (`docs/backend/billing.md`), a third set: `media_limits(principal, byok=, paid=)` gives a paid account `MediaTier.PAID` (`PAID_MAX_DURATION_SECONDS` / `PAID_MAX_FILE_SIZE_MB`, defaulting to the signed-in BYOK numbers) with or without a key, the larger of paid and BYOK when it sends one; `GET /api/limits` gains `paid`. Paid runs take the long job and the per-account long-run slot like signed-in BYOK runs (`MediaTier.long_job`).

**Limits enforced**: file extension (`.mp3`/`.mp4`/`.mov` only), `MAX_FILE_SIZE_MB` (both during streamed upload and post-download for URL sources), `MAX_DURATION_SECONDS` via `enforce_duration_cap` (checked once for uploads, checked again after download for URL/S3 sources since those weren't probed synchronously by the request handler). `enforce_duration_cap` **returns the probed duration** (seconds, float) so callers can record it on the run (`Run.duration_seconds`); `captions.py` likewise carries yt-dlp's reported `duration` on `CaptionTrack.duration_seconds`.

**yt-dlp cookies**: exactly one of `YTDLP_COOKIES_FILE` or `YTDLP_COOKIES_FROM_BROWSER` may be configured — both set raises `MediaValidationError`. Needed for login-gated sources (Instagram in particular); the download-error message is rewritten with cookie-setup guidance when yt-dlp reports Instagram returned an empty response.

**Download size (720p soft cap)**: `_format_options` gives yt-dlp `format: "bestvideo*+bestaudio/best/bestaudio"` plus `format_sort: ["res:<YTDLP_MAX_HEIGHT>"]` (default **720**; `<= 0` drops `format_sort` and restores yt-dlp's plain "best"). The sort prefers the largest variant at or under the cap; a source with nothing that small gets its **smallest** variant above it rather than failing, and formats of unknown height (progressive social-media mp4s) stay eligible. A `[height<=720]` filter in the selector was rejected because its fallback (`/bv*+ba/b`) jumps to the source's best (4K) exactly when no small variant exists, and the filter drops unknown-height formats. Audio-only sources and the caption fallback (`captions.py`, its own options, `download=False`) are unaffected; split streams still merge through the directory of the resolved `ffmpeg` (`FFMPEG_LOCATION`). Why: a 3:33 YouTube link fetched a 229 MiB best format and hit a mid-download 403; FFmpeg re-encodes everything anyway and Gemini doesn't need more than 720p. The probe still wins for `width`/`height`, so the poster/dims path doesn't care.

**Blocked downloads (403/429)**: `_download_failure` maps `HTTP Error 403`, `HTTP Error 429` and `Too Many Requests` to "The site blocked this download for now - the video itself is fine. Try again in a few minutes." These entries sit **after** the private/unavailable/region markers in `_KNOWN_DOWNLOAD_FAILURES`, so a genuine one of those keeps its own sentence. Before this, a mid-download 403 on a public YouTube video fell through to the generic "may be private, deleted, or region-locked", which was untrue. The sentence names only the cause and timing because the frontend's `downloading`-stage `recoveryAdvice` already adds "download the video and upload the file instead". YouTube's "Sign in to confirm you're not a bot" keeps its existing sentence ("YouTube is blocking automated downloads from this server.").

**Geo-blocks**: "This video isn't available in this server's region." is returned when the `DownloadError`'s `exc_info` holds a `GeoRestrictedError` (any extractor, any wording), or when the text carries one of yt-dlp's real geo markers: `available in your country` (YouTube's subreason "The uploader has not made this video available in your country", `extractor/youtube/_video.py`), `not available from your location` / `due to geo restriction` (`raise_geo_restricted`'s default, `extractor/common.py`), or `You might want to use a VPN or a proxy server` (the hint `YoutubeDL.py` appends to every `GeoRestrictedError` it reports). These sit ahead of "Video unavailable" and the 403/429 entries, because a geo-blocked video can also surface an HTTP 403 and the region is the true cause. Strings checked against yt-dlp 2026.07.04; the old marker `not available in your country` never matched YouTube's wording.

**Source metadata**: `download_url` also builds a `domain.entities.SourceMetadata` from the same `extract_info()` call already needed for the download itself (`platform` from `extractor_key`, plus `title`/`uploader`/`uploader_url`/`description`/`upload_date`/`like_count`/`view_count`/`comment_count`, all `dict.get()`-based so missing fields are just `None`) and attaches it to the returned `SavedUpload`. This is platform post metadata, distinct from the Gemini-generated `VideoAnalysis` — see `docs/backend/run-processing.md` for how it's persisted onto the `Run`. File uploads (`uploads.save_upload`) never set this field.

## History poster: thumbnail and display size (Phase 5a)

`MediaService.describe_visuals(media_path=, thumbnail_urls=, width=, height=, duration_seconds=) -> MediaVisuals` (the `MediaProcessor` port method) produces what the browser stores in its IndexedDB History. It **never raises**: the whole step is wrapped in a 45 s `wait_for` and any error returns empty `MediaVisuals`.

**Dimensions**: `ffprobe -select_streams v:0 -show_entries stream=width,height:stream_disposition=attached_pic:stream_tags=rotate:stream_side_data=rotation -of json`. A ±90/270° rotation (display-matrix side data on new files, `rotate` tag on old ones) swaps width/height so phone portrait video reports portrait. An `attached_pic` stream (MP3 cover art) counts as no video. The probe wins; yt-dlp's `width`/`height` are the fallback (and the only source on the captions path). Audio → `None`.

**Thumbnail, in order**:
1. yt-dlp's `info["thumbnail"]`, then the best `info["thumbnails"]` entry (by `preference`, then area) — at most two URLs, http(s) only. Fetched with `urllib` through `validate_public_url` **and** `ValidatingRedirectHandler` (every redirect hop re-checked), 8 s timeout, **3 MB cap** (declared `Content-Length` and the actual body both checked).
2. Otherwise (no URL, fetch failed, or ffmpeg couldn't decode it): one frame from the local media at `min(1s, 10% of duration)`, retried at 0 s if that seek finds nothing. Only when the probe found a real video stream — audio never gets a frame.
3. Otherwise `None`. Captions-only runs have no media, so step 2 does not apply.

**Encoding** (`encode_thumbnail`): stdin→stdout pipes, no temp files. `scale='min(320,iw)':'min(320,ih)':force_original_aspect_ratio=decrease` (shrinks, never enlarges, keeps aspect), mjpeg at `-q:v` 4 → 7 → 11 → 16 → 23 → 31 until ≤ **20 KB** (hard ceiling); if even q31 is over, the side steps down 320 → 240 → 180 → 120 → 80. Undecodable input stops after one attempt. Every ffmpeg/ffprobe call has a 15 s deadline and is killed on timeout or cancellation. Measured on the real binaries in the tests: a 1280×720 test pattern poster → 10.2 KB at 320×180; a 1920×1080 pure-noise image (near JPEG worst case) → 13.9 KB; a rotated 1280×720 phone clip's frame → 10.3 KB at 180×320.

## `TEMP_DIR` is validated at startup, and why it has to be

`validate_temp_dir` runs from **both** entry points — `api/app.py`'s
`lifespan` and `worker/settings.py`'s `startup` — and refuses to boot on a
`TEMP_DIR` that is not an absolute POSIX path, cannot be created, or is not
writable. It creates the directory as part of that check.

This exists because of a real production failure. The dev deployment had a
Railway service variable `TEMP_DIR` set to
`C:/Users/.../AppData/Local/Temp/videolens` — a Windows path carried into a
Linux container, almost certainly copied from a local `.env`. Nothing in the
repo said this: `config.py`, `backend/Dockerfile`, `backend/.env.example` and
`docker-compose.yml` all say `/tmp/videolens`, and an environment variable
overrides the Dockerfile's `ENV`, so it was invisible to code review, CI and
tests alike.

What made it genuinely hard to catch is that **it did not fail where it was
wrong**:

- `C:` is a legal directory name on Linux, so the old bare
  `os.makedirs(temp_dir)` at import time *succeeded*, quietly creating a
  relative `./C:/Users/...` tree next to the process. Startup reported
  healthy.
- yt-dlp then downloaded into that junk directory without complaint, so the
  `downloading` stage went green.
- FFmpeg was the first component strict enough to object, because it reads
  everything before the first colon of an output filename as a protocol
  scheme. It saw `C`, found no such protocol, and failed the run with
  `Protocol not found` at the `normalizing` stage — a media-looking error,
  several steps removed from the actual cause, and only on runs that got
  that far.

The old import-time `os.makedirs` was removed with this change; it was the
thing hiding the misconfiguration, not a safety net. `create_run_dir` still
creates per-run subdirectories as before.

**Known issue / non-issue**: none currently identified beyond what's already handled — this is one of the more defensively-written areas of the codebase.

**Tests** (all under `backend/tests/infrastructure/media/`)
- `test_net.py` — the SSRF guard: scheme, embedded credentials, URL length, unresolvable host, and the case where only the *second* resolved address is private. Plus `is_public_address` on the translation forms (IPv4-mapped, NAT64) and the pinned opener: the approved address is what the connection dials, a private target is refused before connecting, a proxied request is checked but not pinned.
- `test_ytdlp_downloader.py` — cookie-option building, the `_download_failure` user/operator split, and the `SourceMetadata` mapping.
- `test_resolver_chain.py` — order, fall-through, skipping non-claiming resolvers, which error surfaces, metadata preservation, and that a non-`MediaValidationError` is not swallowed.
- `test_captions.py` — cue/json3/XML parsing, rolling-duplicate collapsing, and track/format selection preferences.
- `test_thumbnails.py` — URL/dimension picking from yt-dlp info, rotation-aware probe parsing (side data, legacy tag, 180°, cover art), fetch caps and SSRF refusal, the quality-then-size ladder and the 20 KB ceiling (mocked ffmpeg), the full fallback order (mocked), `describe_visuals` precedence, and real-ffmpeg end-to-end cases (skipped without ffmpeg): sizes, aspect, no upscaling, rotated video → portrait dims and frame, garbage fetch → frame, audio → nothing, seek past the end → retry at 0.
- `test_media_limits_adapters.py` — every adapter honours the `limits` it is given (upload size, duration probe, yt-dlp options and post-download size, direct HTTP Content-Length, caption duration) and falls back to the standard set without one.
- `tests/application/test_media_limits.py` — the resolver per caller, the floor, the hint wording, and admission at 179/181/599/601 s and 199/201/499/501 MB for the four caller combinations.
- `test_direct_http_resolver.py` — `can_handle` boundaries, both size-cap paths, that an HTTP status stays in `log_detail` and off the screen, empty body, run-dir cleanup on failure, and the private-address redirect refusal.

No test coverage for `ffmpeg.py` directly (it requires an actual ffmpeg binary). `test_uploads.py` covers `validate_temp_dir`; two of its cases are POSIX-only by construction (a Windows path *is* absolute on Windows, so the check cannot fire) and fail when the suite is run on Windows. CI runs on Linux.

## Changelog

- 2026-08-21 · main session · every message rewritten for the person on screen; yt-dlp/FFmpeg stderr and the FFMPEG_LOCATION / YTDLP_COOKIES_* hints moved to log_detail. See ../error-messaging.md
- 2026-08-29 · main session · extracted the SSRF guard into `net.py`; put `download_url` behind an ordered `ResolverChain` and added `DirectHttpResolver` as the fallback route
- 2026-08-29 · main session · added `captions.py` (subtitle salvage) and shared `_source_metadata_from_info` between the download and caption paths
- 2026-08-29 · main session · merged dev: `net.py` carries dev's user-facing wording plus `log_detail`, and the resolvers follow the same split
- 2026-10-28 · claude (session ccr-ee9ca9d3) · fixed `_has_video_stream` misreading streams with side data as audio-only (broke a video-only Instagram reel in dev)
- 2026-11-01 · backend agent (Phase 3) · `enforce_duration_cap` returns the probed duration; `CaptionTrack` carries yt-dlp's `duration`
- 2026-11-01 · main session · `test_uploads.py`: the two Windows-drive-path rejection tests now skip on Windows (`C:/...` is genuinely absolute there); they still run on the Linux CI/container the check exists for
- 2026-11-01 · backend agent (Phase 5a) · `thumbnails.py` + `MediaService.describe_visuals` (SSRF-guarded poster fetch, frame fallback, ≤320 px / ≤20 KB JPEG, rotation-aware ffprobe dims); yt-dlp/captions carry `thumbnail_urls`/`width`/`height` hints; redirect handler moved to `net.py`
- 2026-11-02 · backend agent (720p download cap) · yt-dlp downloads soft-capped at 720p via `format_sort: ["res:N"]` (new `YTDLP_MAX_HEIGHT`, default 720, `<= 0` = no cap); `FormatCapTests` assert the options
- 2026-11-02 · backend agent (720p download cap) · yt-dlp 403/429/`Too Many Requests` now say "The site blocked this download for now..." instead of the generic private/deleted sentence (owner-approved); flagged the region-marker gap
- 2026-11-02 · backend agent (geo-block message) · region-lock detection now matches yt-dlp's real geo wording plus the `GeoRestrictedError` type, ahead of "Video unavailable" and 403/429; closes the region-marker gap
- 2026-11-07 · security-check · `net.py`: `is_public_address` rejects NAT64/mapped forms wrapping private IPv4; `build_public_opener` pins every urllib connection (first request and each redirect) to the address the check approved, closing the DNS-rebinding race; direct-HTTP resolver and thumbnail fetch use it
- 2026-11-13 · backend agent · limits chosen per caller (`MediaLimits` from `EntitlementResolver.media_limits`) and passed to every check: upload, duration probe, yt-dlp, direct HTTP, captions; over-limit messages gain a sign-in/key hint; yt-dlp size sentence reworded
- 2026-11-13 · backend agent · paid media tier (`MediaTier.PAID`, `PAID_MAX_*`), `paid` in `GET /api/limits`
