from fastapi import Depends, Header
from starlette.requests import Request

from ...container import container
from ...domain.entities import AuthMethod, Principal
from ...domain.errors import AuthenticationError, ForbiddenError


async def get_principal(
    request: Request,
    authorization: str = Header(default=""),
    x_client_id: str = Header(default=""),
    x_api_key: str = Header(default=""),
) -> Principal:
    """Resolve who is calling (`IdentifyCallerUseCase`: API key, then bearer
    token, then X-Client-ID). Domain errors map to 400/401/503 in
    `error_handlers.py`.

    The resolved principal is left on `request.state` for the rate limiter:
    slowapi's route decorator checks the limit inside the endpoint call,
    after FastAPI has resolved this dependency, so `rate_limiter.quota_key`
    keys on exactly this principal rather than resolving it a second time.
    """
    principal = await container.identify_caller_use_case.resolve(
        authorization=authorization, api_key=x_api_key, client_id=x_client_id
    )
    request.state.principal = principal
    return principal


async def get_signed_in_principal(principal: Principal = Depends(get_principal)) -> Principal:
    """Any authenticated caller: a signed-in person or an API key."""
    if not principal.authenticated:
        raise AuthenticationError("Sign in to use this.")
    return principal


async def require_person(principal: Principal = Depends(get_principal)) -> Principal:
    """A signed-in person, and only that: anonymous is 401, an API key 403.

    For key management (and, in phase 3, account deletion). An API key is
    authenticated, so `authenticated` alone would let a leaked agent key mint
    more keys; the credential has to be an identity-provider session."""
    if not principal.authenticated:
        raise AuthenticationError("Sign in to use this.")
    if principal.method is not AuthMethod.TOKEN:
        raise ForbiddenError("This needs a signed-in session, not an API key.")
    return principal
