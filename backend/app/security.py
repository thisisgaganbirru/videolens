import asyncio
import hashlib
import re
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from .config import settings

CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


@dataclass(frozen=True)
class Principal:
    subject: str
    authenticated: bool


def quota_key_from_headers(authorization: str, client_ip: str) -> str:
    # Keyed by IP, not the client-supplied X-Client-ID: that header is
    # self-reported and free to regenerate, so it carries no quota weight.
    if authorization.startswith("Bearer "):
        digest = hashlib.sha256(authorization.encode()).hexdigest()[:32]
        return f"token:{digest}"
    return f"ip:{client_ip}" if client_ip else "anonymous"


def _decode_token(token: str) -> dict:
    if not settings.auth_jwks_url or not settings.auth_issuer or not settings.auth_audience:
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    signing_key = PyJWKClient(settings.auth_jwks_url).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=settings.auth_audience,
        issuer=settings.auth_issuer,
    )


async def get_principal(
    authorization: str = Header(default=""),
    x_client_id: str = Header(default=""),
) -> Principal:
    if authorization.startswith("Bearer "):
        try:
            claims = await asyncio.to_thread(_decode_token, authorization.removeprefix("Bearer "))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Invalid access token.") from exc
        subject = str(claims.get("sub", "")).strip()
        if not subject:
            raise HTTPException(status_code=401, detail="Access token has no subject.")
        return Principal(subject=f"user:{subject}", authenticated=True)

    if not settings.allow_anonymous:
        raise HTTPException(status_code=401, detail="Sign in is required.")
    if not CLIENT_ID_PATTERN.fullmatch(x_client_id):
        raise HTTPException(status_code=400, detail="A valid X-Client-ID header is required.")
    return Principal(subject=f"client:{x_client_id}", authenticated=False)
