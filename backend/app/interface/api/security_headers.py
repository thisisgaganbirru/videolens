"""Response headers every API answer carries.

The API serves JSON to a cross-origin `fetch`, so most browser hardening
headers do little here - but they cost nothing and close the few cases that
do apply: a JSON document opened directly in a tab (`nosniff`, the CSP and
frame denial keep it inert), a run result cached by an intermediary or the
browser's back/forward cache (`no-store`: every answer is per-caller and
short-lived), and a plain-http hop to the API host (`Strict-Transport-
Security`, which browsers only honour over https, so it is harmless for
local runs). The frontend sends its own set for the pages it serves
(`frontend/security/csp.mjs`); this is the API's half.

Pure ASGI, no Starlette `BaseHTTPMiddleware`: that class buffers streaming
responses and swallows the request body on early returns, neither of which
an uploads endpoint can afford.
"""

from starlette.datastructures import MutableHeaders

SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
    ("Referrer-Policy", "no-referrer"),
    ("Strict-Transport-Security", "max-age=31536000"),
    ("Cache-Control", "no-store"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS:
                    # A handler that set its own value (a future cacheable
                    # endpoint, say) wins; these are defaults, not overrides.
                    if name not in headers:
                        headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
