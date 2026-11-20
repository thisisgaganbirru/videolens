"""Request body size guard, before any route reads a byte.

`file: UploadFile = File()` makes FastAPI parse the whole multipart body
(spooling the file to a temp file) before the handler runs, so terms,
admission, the rate limit and `MAX_FILE_SIZE_MB` all come after the upload
is already on disk. This cuts a request off first: a `Content-Length` over
the limit is answered 413 straight away, and a body with no length, a false
one or a chunked one is counted as it streams and stopped at the limit.

The limit here is a ceiling, not the caller's limit: nobody is identified
yet, so `POST /api/runs` allows the largest upload any caller may send
(plus multipart framing), and the exact per-caller check stays where the
upload is saved (`media/uploads.py`). Every other route gets a small JSON
bound; the Stripe webhook a larger one, and its raw body reaches the
signature check untouched (this only counts bytes).

Pure ASGI, like `security_headers.py`, and added inside CORS so a 413 still
carries the CORS headers the frontend needs to read it.
"""

import json

from starlette.exceptions import HTTPException

# Multipart boundaries, part headers and the small form fields beside the
# file; generous, since a false 413 on a legal upload is the worse mistake.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024
# JSON routes (API keys, checkout) send a few hundred bytes.
DEFAULT_MAX_BODY_BYTES = 1024 * 1024
# Stripe events are small, but an invoice with many lines is not tiny.
WEBHOOK_MAX_BODY_BYTES = 4 * 1024 * 1024

TOO_LARGE_MESSAGE = "That upload is too large."


class _BodyTooLarge(HTTPException):
    """Raised from `receive` once a streamed body passes the limit. An
    HTTPException so FastAPI's body parsing re-raises it as is (it turns any
    other error there into a 400) and its handler answers `{"detail": ...}`."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail=TOO_LARGE_MESSAGE)


class BodySizeLimitMiddleware:
    def __init__(self, app, *, upload_max_bytes: int) -> None:
        self.app = app
        self._limits = {
            ("POST", "/api/runs"): upload_max_bytes + MULTIPART_OVERHEAD_BYTES,
            ("POST", "/api/billing/webhook"): WEBHOOK_MAX_BODY_BYTES,
        }

    def _limit(self, scope) -> int:
        return self._limits.get((scope.get("method", ""), scope.get("path", "")), DEFAULT_MAX_BODY_BYTES)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit(scope)
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            await _send_too_large(send)
            return

        received = 0
        started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            # Normally the route's error handler already answered; this is
            # for a body read outside one (a middleware, say).
            if not started:
                await _send_too_large(send)


def _content_length(scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _send_too_large(send) -> None:
    body = json.dumps({"detail": TOO_LARGE_MESSAGE}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                # Unread body left on the socket: never reuse the connection.
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
