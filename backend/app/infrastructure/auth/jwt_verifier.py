import jwt
from jwt import PyJWKClient

from ..config import Settings


class AuthNotConfiguredError(RuntimeError):
    pass


class JwtVerifier:
    """TokenVerifier adapter backed by a remote JWKS endpoint (OIDC).

    The JWKS URL and issuer are what make a token verifiable at all, so both
    are required. The audience is optional: Clerk's session tokens carry no
    `aud` claim unless a JWT template adds one, and the same is true of
    several other providers' default tokens. When `AUTH_AUDIENCE` is set the
    claim is enforced; when it is blank the check is skipped rather than
    every token being rejected for lacking a claim nobody configured.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks_client: PyJWKClient | None = None

    def _jwks(self) -> PyJWKClient:
        # One client per process so the key set is cached between requests
        # instead of being fetched on every bearer token.
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self._settings.auth_jwks_url)
        return self._jwks_client

    def decode(self, token: str) -> dict:
        settings = self._settings
        if not settings.auth_jwks_url or not settings.auth_issuer:
            raise AuthNotConfiguredError("Authentication is not configured.")
        signing_key = self._jwks().get_signing_key_from_jwt(token)
        return self.decode_with_key(token, signing_key.key)

    def decode_with_key(self, token: str, key) -> dict:
        """Verify `token` against an already-resolved public key.

        Split out from `decode` so the claim checks can be exercised without
        a JWKS endpoint; `decode` is the JWKS lookup plus this.
        """
        settings = self._settings
        options = {"verify_aud": bool(settings.auth_audience)}
        return jwt.decode(
            token,
            key,
            algorithms=["RS256", "ES256"],
            audience=settings.auth_audience or None,
            issuer=settings.auth_issuer,
            options=options,
        )
