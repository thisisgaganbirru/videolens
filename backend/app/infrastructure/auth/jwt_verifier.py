import jwt
from jwt import PyJWKClient

from ..config import Settings


class AuthNotConfiguredError(RuntimeError):
    pass


class JwtVerifier:
    """TokenVerifier adapter backed by a remote JWKS endpoint (OIDC)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def decode(self, token: str) -> dict:
        settings = self._settings
        if not settings.auth_jwks_url or not settings.auth_issuer or not settings.auth_audience:
            raise AuthNotConfiguredError("Authentication is not configured.")
        signing_key = PyJWKClient(settings.auth_jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
        )
