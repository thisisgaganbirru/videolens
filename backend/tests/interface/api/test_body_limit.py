"""The body-size guard answers 413 before a route reads past the limit,
whether the client declares the length or streams it, and keeps CORS on the
answer so the frontend can read it."""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.testclient import TestClient

from app.container import container
from app.domain.entities import Run, RunStatus
from app.interface.api import body_limit
from app.interface.api.app import app
from app.interface.api.body_limit import BodySizeLimitMiddleware

ORIGIN = "https://localhost"


def _guarded_app(upload_max_bytes: int) -> FastAPI:
    """The same stack order as app.py: CORS outside the guard."""
    small = FastAPI()
    small.state.read = []

    @small.post("/api/runs")
    async def upload(file: UploadFile = File(...)) -> dict:
        data = await file.read()
        small.state.read.append(len(data))
        return {"size": len(data)}

    @small.post("/api/billing/webhook")
    async def webhook(request: Request) -> dict:
        return {"size": len(await request.body())}

    @small.post("/api/keys")
    async def keys(request: Request) -> dict:
        return {"size": len(await request.body())}

    small.add_middleware(BodySizeLimitMiddleware, upload_max_bytes=upload_max_bytes)
    small.add_middleware(CORSMiddleware, allow_origins=[ORIGIN], allow_methods=["POST"])
    return small


def _chunks(total: int, size: int = 64 * 1024):
    sent = 0
    while sent < total:
        n = min(size, total - sent)
        sent += n
        yield b"x" * n


class BodySizeLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _guarded_app(upload_max_bytes=2 * 1024 * 1024)
        self.client = TestClient(self.app)
        self.limit = 2 * 1024 * 1024 + body_limit.MULTIPART_OVERHEAD_BYTES

    def test_oversized_content_length_is_413_with_cors(self) -> None:
        response = self.client.post(
            "/api/runs",
            content=b"x" * (self.limit + 1),
            headers={"Origin": ORIGIN, "Content-Type": "multipart/form-data; boundary=b"},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"detail": body_limit.TOO_LARGE_MESSAGE})
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        self.assertEqual(self.app.state.read, [])

    def test_streamed_body_without_length_is_cut_off(self) -> None:
        boundary = "bnd"
        head = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.mp4\"\r\n"
            "Content-Type: video/mp4\r\n\r\n"
        ).encode()
        consumed = []

        def body():
            yield head
            for chunk in _chunks(self.limit * 2):
                consumed.append(len(chunk))
                yield chunk

        response = self.client.post(
            "/api/runs",
            content=body(),
            headers={"Origin": ORIGIN, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"detail": body_limit.TOO_LARGE_MESSAGE})
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        self.assertEqual(self.app.state.read, [])

    def test_normal_upload_still_works(self) -> None:
        response = self.client.post("/api/runs", files={"file": ("a.mp4", b"x" * 1024 * 1024, "video/mp4")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"size": 1024 * 1024})

    def test_json_routes_are_bounded_too(self) -> None:
        response = self.client.post("/api/keys", content=b"{" + b" " * body_limit.DEFAULT_MAX_BODY_BYTES + b"}")
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.post("/api/keys", json={"name": "k"}).status_code, 200)

    def test_webhook_gets_its_own_larger_bound_and_the_raw_body(self) -> None:
        payload = b"{" + b" " * (2 * 1024 * 1024) + b"}"
        response = self.client.post("/api/billing/webhook", content=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"size": len(payload)})
        too_big = b"x" * (body_limit.WEBHOOK_MAX_BODY_BYTES + 1)
        self.assertEqual(self.client.post("/api/billing/webhook", content=too_big).status_code, 413)


class AppWiringTests(unittest.TestCase):
    """The real app: the guard is wired and follows the largest media limit."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_ceiling_is_the_largest_tier_plus_overhead(self) -> None:
        ceiling = container.entitlements.largest_file_size_bytes
        self.assertGreaterEqual(ceiling, container.entitlements.signed_in_byok.max_file_size_bytes)
        self.assertGreaterEqual(ceiling, container.entitlements.paid.max_file_size_bytes)

    def test_real_app_refuses_an_oversized_declared_body_with_cors(self) -> None:
        ceiling = container.entitlements.largest_file_size_bytes + body_limit.MULTIPART_OVERHEAD_BYTES

        def body():
            yield b"x"

        # Declares more than the ceiling without sending it: refused on the
        # header alone, before the use case is reached.
        with patch.object(container.create_run_use_case, "execute", AsyncMock()) as execute:
            response = self.client.post(
                "/api/runs",
                content=body(),
                headers={
                    "Origin": ORIGIN,
                    "Content-Length": str(ceiling + 1),
                    "Content-Type": "multipart/form-data; boundary=b",
                },
            )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        execute.assert_not_called()

    def test_real_app_accepts_a_small_upload(self) -> None:
        now = datetime(2026, 11, 20, tzinfo=timezone.utc)
        run = Run(
            run_id="r1", owner_id="client:test-client-0123456789", status=RunStatus.QUEUED, created_at=now, updated_at=now
        )
        with patch.object(container.create_run_use_case, "execute", AsyncMock(return_value=run)):
            response = self.client.post(
                "/api/runs",
                files={"file": ("a.mp4", b"x" * 2048, "video/mp4")},
                data={"accept_terms": "true"},
                headers={"X-Client-ID": "test-client-0123456789"},
            )
        self.assertEqual(response.status_code, 202)


if __name__ == "__main__":
    unittest.main()
