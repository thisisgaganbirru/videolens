# Error messaging

How a failure becomes a sentence on someone's screen, and where the rest of it
goes. Spans both sides: the backend decides *what happened*, the frontend
decides *what to try next*.

**Files**
- `backend/app/domain/errors.py` — `UserFacingError` and its subclasses.
- `backend/app/application/process_run.py` — logs `log_detail`, stores only the message.
- `backend/app/infrastructure/media/ytdlp_downloader.py` — `_download_failure`.
- `backend/app/infrastructure/media/ffmpeg.py` — `_clock`, plus tool-failure detail.
- `backend/app/infrastructure/ai/gemini_engine.py` — `_as_domain_error`.
- `backend/app/interface/api/app.py` — `_rate_limited`.
- `frontend/components/RunStatusView.tsx` — `recoveryAdvice`.

## The two-audience split

`UserFacingError(message, log_detail=...)` is the whole mechanism. `str(exc)` is
shown verbatim on screen; `log_detail` is written to the log by
`ProcessRunUseCase._log_failure` and **never** stored on the run — storing it
would put it straight back on the phone.

This exists because the two audiences used to share one string. The messages
were written when the backend ran on the author's laptop, where the reader *was*
the operator. Deploying to Railway made them wrong without changing a line:
"Configure YTDLP_COOKIES_FILE on the server" started reaching people holding a
phone, and yt-dlp's and FFmpeg's raw stderr went with it — unbounded, unreviewed
text including file paths and "Confirm you are on the latest version using
yt-dlp -U". Same class of bug as the `TEMP_DIR` and cache-mount incidents: a
local-dev assumption surviving into a deployment.

Three rules for anything added here:

1. **Name the cause in the user's terms.** "This post isn't public", not
   "Instagram sent an empty media response".
2. **Never print an env var, a CLI flag, a library name, or raw stderr.** Those
   are `log_detail`, always.
3. **One action, and only when it can help.** See `recoveryAdvice` below.

## Cause vs. action

`RunStatusView` renders two paragraphs, and they have different jobs: the
backend's message says *why*, and `recoveryAdvice` says *what next*. Before
2026-08-21 both tried to do both, and both were keyed on the wrong thing.

`recoveryAdvice` chooses on **the stage the run died at**, not on `sourceKind`.
The case that forced this: a run downloaded, normalized and uploaded
successfully, then Gemini answered 503 — and the screen said "Try a different
URL, or upload the file directly instead." A different URL would have failed in
exactly the same place. Anything at or after `uploading_to_gemini` is ours, and
saying so beats sending someone off to re-do work that was already good.

The stage survives the failure because `set_error` writes only `status` and
`error`; the last stage polled stays on the record and in client state. That is
also why the pipeline still shows its ticks on a failed run.

## Transient upstream failures

`GeminiEngine._as_domain_error` maps 429/500/502/503/504 to
`AnalysisUnavailableError` — a distinct type precisely so a busy model does not
arrive as the generic `except Exception` catch-all. 4xx other than 429 is left
alone: it will not succeed on a retry and is not the caller's doing, so it stays
masked with a traceback in the log.

`.code` on `google.genai.errors.APIError` is the status int (verified against
the library, not assumed).

## Rate limiting

slowapi's stock handler answers `{"error": ...}`, but every other error in this
API answers `{"detail": ...}` and that is the key `runsGateway` reads. A
rate-limited caller therefore used to see the bare fallback "Could not create
run (429)". `_rate_limited` replaces it.

## Known issues

- **Copy lives in the backend.** A reason code on the run schema with a
  frontend copy table would be the more correct split, and would let the UI do
  things prose cannot — offer an actual upload control for the login-gated case
  rather than describing one. Deliberately deferred: it needs a schema field, a
  mapping table, and changes at every raise site, and the two-field version
  captures most of the value.
- **The retry policy is still weak.** `analyze_with_retry` does 2 attempts with
  a flat 2s sleep and treats every exception alike. Google's own 503 says spikes
  are "usually temporary", but two seconds is the same overloaded moment.
  Exponential backoff with jitter, more attempts for transient statuses, and no
  retry at all for 4xx is the fix — tracked separately because it changes
  runtime behaviour rather than copy.
- **`_clock` has no hours component**, so a 90-minute input would read "90:00".
  Unreachable while `MAX_DURATION_SECONDS` is 180.
- **Not visually verified.** Typechecked and built clean; no screenshot.

**Tests**: `backend/tests/infrastructure/media/test_ytdlp_downloader.py`
(message/detail split per failure kind),
`backend/tests/infrastructure/ai/test_gemini_engine.py` (status
classification), `backend/tests/application/test_process_run.py` (`log_detail`
never reaches the run). No frontend test runner exists — see
`frontend/run-analysis-hook.md`.

## Changelog

- 2026-08-21 · main session · introduced UserFacingError's message/log_detail split, rewrote every leaking message, added AnalysisUnavailableError for Gemini 429/5xx, gave rate limiting a `detail`-shaped response, keyed recovery advice on the failed stage, and removed the dead `data-error-kind` attribute
