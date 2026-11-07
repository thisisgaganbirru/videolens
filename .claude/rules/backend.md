---
paths:
  - "backend/**"
---

# Backend rules

- `requirements.txt` is a universal, hash-locked compile of
  `requirements.in`. Regenerate only with
  `uv pip compile requirements.in --generate-hashes --python-version 3.13 --universal --output-file requirements.txt`.
  Plain `pip-compile` drops the PEP 508 markers and CI fails the job (this
  broke Windows installs once, Dependabot PR #95).
- Every adapter takes `Settings` in its constructor; never read the
  module-level `settings` in new code. `interface/api/rate_limiter.py` is the
  one existing exception and is recorded as debt.
- `domain/` and `application/` import no framework or driver. Exceptions the
  interface layer may catch live in `domain/errors.py`. A user-facing error
  carries a phone-readable message and an operator-only `log_detail`; never
  put internals in the message.
- `VideoAnalysis` is Gemini's response schema. Do not add server-known facts
  to it (that is why `AnalysisCompleteness` is a separate field on the run).
- Publisher metadata (titles, captions) is untrusted text. It reaches the
  prompt only through `ai/source_context.py`, fenced and labelled.
- New URL source: a `SourceResolver` in `media/resolvers/`, added to the
  chain in `MediaService.__init__`, fetching through `media/net.py`. New
  dependency worth reporting: a `CapabilityProbe` in `health/probes.py`,
  appended in `container.py`.
- `interface/api/security_headers.py` is pure ASGI and added last so it is
  outermost; never swap it for `BaseHTTPMiddleware` (it buffers streaming
  bodies). The client IP is `policies.client_ip_from_forwarded` with
  `TRUSTED_PROXY_HOPS`; do not read the first `X-Forwarded-For` entry.
- A thumbnail, duration, source-metadata or free-run-refund failure must
  never fail an otherwise healthy run; log and swallow, as the existing code
  does.
- Tests mirror `app/` under `tests/` and construct adapters with an explicit
  `Settings(...)`; use-case tests use `tests/application/fakes.py`. Run
  `compileall` before `unittest`, as CI does.
