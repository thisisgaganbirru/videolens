# API response headers

Every answer the API sends carries a fixed set of hardening headers. The
frontend has its own set for the pages it serves (`../frontend/security-headers.md`);
this is the API's half.

**Files**
- `backend/app/interface/api/security_headers.py` — `SECURITY_HEADERS` and
  `SecurityHeadersMiddleware` (pure ASGI; not `BaseHTTPMiddleware`, which
  buffers streaming responses and interferes with request bodies).
- `backend/app/interface/api/app.py` — added last, so it is the outermost
  middleware and covers CORS preflights, rate-limit refusals and error
  responses too.

**Headers** (defaults: a handler that sets its own value wins):

| Header | Value | Why |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | A JSON document opened in a tab is never sniffed into something that runs. |
| `X-Frame-Options` / CSP `frame-ancestors` | `DENY` / `'none'` | Nothing here is meant to be framed. |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` | Keeps a directly-opened response inert. |
| `Referrer-Policy` | `no-referrer` | The API never needs to be a referrer. |
| `Strict-Transport-Security` | `max-age=31536000` | Browsers honour it over https only; harmless on local http. No `includeSubDomains`: the host's siblings are not this app's to pin. |
| `Cache-Control` | `no-store` | Every answer is per-caller and short-lived; run results carry transcripts and must not sit in a shared cache or the back/forward cache. |

**Tests**: `backend/tests/interface/api/test_security_headers.py` (present on a
route, on a 404, on a CORS preflight; run answers are `no-store`).

## Changelog

- 2026-11-07 · security-check · created: `SecurityHeadersMiddleware` on every API response
