import asyncio

from fastapi import Depends, Header, HTTPException

from ...container import container
from ...domain.entities import Principal
from ...domain.errors import AuthenticationError
from ...infrastructure.auth.jwt_verifier import AuthNotConfiguredError
from ...infrastructure.persistence.api_key_repository import looks_like_api_key


async def get_principal(
    authorization: str = Header(default=""),
    x_client_id: str = Header(default=""),
    x_api_key: str = Header(default=""),
) -> Principal:
    """Resolve who is calling, in order of how strong the credential is.

    1. An API key (`X-Api-Key`, or a `Bearer vl_live_...`): a workspace's
       key, issued from the account panel, used by the MCP server and scripts.
    2. A bearer token from the identity provider: a signed-in person.
    3. `X-Client-ID`: an anonymous browser, when the deployment allows it.
    """
    bearer = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    api_key = x_api_key.strip() or (bearer if looks_like_api_key(bearer) else "")
    if api_key:
        try:
            return await container.identify_caller_use_case.from_api_key(api_key)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    if bearer:
        try:
            claims = await asyncio.to_thread(container.jwt_verifier.decode, bearer)
        except AuthNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail="Authentication is not configured.") from exc
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Invalid access token.") from exc
        try:
            return await container.identify_caller_use_case.from_token_claims(claims)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    if not container.settings.allow_anonymous:
        raise HTTPException(status_code=401, detail="Sign in is required.")
    try:
        return container.identify_caller_use_case.from_client_id(x_client_id)
    except AuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def get_signed_in_principal(principal: Principal = Depends(get_principal)) -> Principal:
    """The routes that manage an account refuse anonymous callers outright
    rather than answering with an empty workspace."""
    if not principal.authenticated:
        raise HTTPException(status_code=401, detail="Sign in to use this.")
    return principal
