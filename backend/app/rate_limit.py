from slowapi import Limiter
from starlette.requests import Request

from .security import quota_key_from_headers


def quota_key(request: Request) -> str:
    return quota_key_from_headers(
        request.headers.get("authorization", ""),
        request.headers.get("x-client-id", ""),
    )


limiter = Limiter(key_func=quota_key, default_limits=[])
