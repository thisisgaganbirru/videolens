import asyncio

from fastapi import Header, HTTPException

from ...container import container
from ...domain.entities import Principal
from ...domain.policies import is_valid_client_id
from ...infrastructure.auth.jwt_verifier import AuthNotConfiguredError


async def get_principal(
    authorization: str = Header(default=""),
    x_client_id: str = Header(default=""),
) -> Principal:
    if authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
        try:
            claims = await asyncio.to_thread(container.jwt_verifier.decode, token)
        except AuthNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail="Authentication is not configured.") from exc
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Invalid access token.") from exc
        subject = str(claims.get("sub", "")).strip()
        if not subject:
            raise HTTPException(status_code=401, detail="Access token has no subject.")
        return Principal(subject=f"user:{subject}", authenticated=True)

    if not container.settings.allow_anonymous:
        raise HTTPException(status_code=401, detail="Sign in is required.")
    if not is_valid_client_id(x_client_id):
        raise HTTPException(status_code=400, detail="A valid X-Client-ID header is required.")
    return Principal(subject=f"client:{x_client_id}", authenticated=False)
